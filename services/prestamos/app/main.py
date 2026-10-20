from shared.runtime import create_app

app = create_app("prestamos")
app.version = '0.6.0'
app.description = 'Transporte Kafka y proyección de Inventario. Modelo y flujo crediticio pendientes.'
