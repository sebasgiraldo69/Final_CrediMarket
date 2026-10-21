"""AC15: pending UI with real consumer interruption; AC16 invalid form and expired JWT."""
import json
import os
from pathlib import Path
from playwright.sync_api import sync_playwright, expect
from phase12_support import BASE, fixtures, docker, inside, evidence, wait_for, api


def main():
    fixture = fixtures()
    folder = evidence('pending_ui.json', {'status': 'STARTED'})
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page()
            page.goto(BASE + '/acceso')
            requests = []
            page.on('request', lambda r: requests.append(r.url) if r.method == 'POST' else None)
            page.get_by_role('button', name='Ingresar', exact=True).click()
            assert page.locator('input:invalid').count() > 0
            assert not requests, 'Invalid form submitted a request'
            page.get_by_label('Correo').fill(fixture['emails']['client'])
            page.get_by_label('Contraseña').fill(fixture['password'])
            page.get_by_role('button', name='Ingresar', exact=True).click()
            expect(page.get_by_role('button', name='Cerrar sesión')).to_be_visible()
            try:
                docker('stop', 'inventario')
                page.get_by_role('navigation').get_by_role('link', name='Catálogo', exact=True).click()
                page.get_by_label('Buscar').fill(fixture['product']['nombre'])
                page.get_by_role('button', name='Solicitar a crédito').click()
                dialog = page.get_by_role('dialog')
                dialog.get_by_label('Plazo').select_option('24')
                dialog.get_by_role('button', name='Enviar solicitud').click()
                expect(dialog.get_by_role('heading', name='Resultado de la solicitud')).to_be_visible()
                dialog.get_by_role('button', name='Ver mis solicitudes').click()
                row = page.locator('tbody tr', has_text=fixture['product']['nombre']).first
                expect(row.locator('.state-pill')).to_have_text('Reservando producto', timeout=15000)
                page.screenshot(path=str(folder / 'AC15-pending.png'), full_page=True)
                # Observe two poll intervals: no fabricated approval while Inventory is down.
                page.wait_for_timeout(4500)
                expect(row.locator('.state-pill')).to_have_text('Reservando producto')
            finally:
                docker('restart', '--no-deps', 'inventario')
            expect(row.locator('.state-pill')).to_have_text('Aprobada', timeout=90000)
            page.screenshot(path=str(folder / 'AC15-recovered.png'), full_page=True)
            try:
                docker('stop', 'productos')
                page.goto(BASE + '/catalogo')
                expect(page.get_by_role('alert')).to_contain_text('no responde', timeout=15000)
                page.screenshot(path=str(folder / 'AC16-api-down.png'), full_page=True)
            finally:
                docker('restart', '--no-deps', 'productos')
            def products_ready():
                try:
                    return api('productos/health')[0] == 200
                except (OSError, ValueError):
                    return False
            wait_for(products_ready)
            page.get_by_role('button', name='Actualizar', exact=True).click()
            expect(page.get_by_role('button', name='Solicitar a crédito').first).to_be_visible(timeout=30000)
            expired = inside('clientes', '''
import time, jwt
from app.security import private_key
token=TOKEN
claims=jwt.decode(token,options={'verify_signature':False})
claims['iat']=int(time.time())-3600; claims['exp']=int(time.time())-60
print(jwt.encode(claims,private_key(),algorithm='RS256'))
'''.replace('TOKEN', repr(fixture['tokens']['client'])))
            page.evaluate('''token => {const s=JSON.parse(sessionStorage.getItem('credimarket.session'));
                s.access_token=token; sessionStorage.setItem('credimarket.session',JSON.stringify(s));}''', expired)
            page.goto(BASE + '/solicitudes')
            expect(page.get_by_text('Tu sesión venció')).to_be_visible()
            expect(page.get_by_label('Contraseña')).to_be_visible()
            evidence('pending_ui.json', {'status': 'PASS', 'real_consumer_interruption': True,
                'pending_observed': True, 'approved_by_polling_after_restart': True,
                'invalid_form_did_not_submit': True, 'genuinely_expired_jwt': True,
                'real_productos_api_outage_recovered': True,
                'product_id': fixture['product']['id']})
        finally:
            browser.close()
    print('PASS AC15 real pending/recovery UI and AC16 invalid form/expired session', flush=True)


if __name__ == '__main__':
    main()
