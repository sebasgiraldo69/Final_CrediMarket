---
name: CrediMarket · Presentación académica
description: Sistema editorial de la presentación HTML de 14 diapositivas.
colors:
  paper: "#f5f3ec"
  ink: "#163d30"
  muted: "#53675b"
  line: "#ccd4c9"
  gold: "#e0ab45"
  soft: "#e5ebe2"
  dark-muted: "#c1d0c4"
  dark-line: "#577260"
  dark-soft: "#244b3d"
typography:
  display:
    fontFamily: "Plex, system-ui, sans-serif"
    fontSize: "clamp(48px, 5.5vw, 86px)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.03em"
  headline:
    fontFamily: "Plex, system-ui, sans-serif"
    fontSize: "clamp(32px, 3.3vw, 52px)"
    fontWeight: 600
    lineHeight: 1.06
    letterSpacing: "-0.03em"
  title:
    fontFamily: "Plex, system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 600
    lineHeight: 1.2
  body:
    fontFamily: "Plex, system-ui, sans-serif"
    fontSize: "21px"
    fontWeight: 400
    lineHeight: 1.48
  source:
    fontFamily: "Plex, system-ui, sans-serif"
    fontSize: "12px"
    fontWeight: 400
    lineHeight: 1.4
rounded:
  control: "6px"
  diagram-node: "8px"
spacing:
  compact: "18px"
  section: "28px"
  generous: "35px"
components:
  control:
    backgroundColor: "{colors.paper}"
    textColor: "{colors.ink}"
    rounded: "{rounded.control}"
    padding: "11px 16px"
  control-hover:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
  focus-panel:
    backgroundColor: "{colors.ink}"
    textColor: "{colors.paper}"
    padding: "36px"
  notes:
    backgroundColor: "{colors.paper}"
    padding: "18px 24px"
---

# Design System: CrediMarket · Presentación académica

## Overview

**Creative North Star: "Editorial académico de CrediMarket"**

Esta documentación describe únicamente la superficie implementada en `presentacion/index.html`: una presentación de lectura para una sustentación académica de 10–15 minutos. No define ni modifica el sistema del frontend de la aplicación.

La dirección conserva la consulta de UI UX Pro Max `fintech technical presentation editorial`, Minimalism & Swiss Style: jerarquía tipográfica, retícula, contraste y espacio. La paleta toma la identidad verde y dorada existente en `frontend/src/style.css`, en lugar de adoptar el morado de la recomendación genérica. El hilo va de la compra a la decisión, luego arquitectura, ML y evidencia. El verde abre y cierra; el marfil sostiene la explicación. Diagramas propios y una captura histórica auténtica dan soporte visual.

**Key Characteristics:**
- Lectura editorial con composiciones variadas según la explicación.
- Un solo tipo local, contraste tonal y divisores finos.
- Navegación manual, fuentes visibles y notas para exponer.

## Colors

La paleta combina verde institucional, marfil y acentos dorados.

### Primary
- **Verde CrediMarket** (`ink`): texto principal, apertura, cierre y paneles que concentran una idea.

### Secondary
- **Dorado de confirmación** (`gold`): resultado de compra y foco visible; también aparece en la partición de datos.

### Neutral
- **Papel marfil** (`paper`): fondo de lectura y texto sobre verde.
- **Verde apagado** (`muted`): párrafos y referencias.
- **Línea suave** (`line`): separaciones y borde de evidencia.
- **Superficie suave** (`soft`): nodos del diagrama arquitectónico.
- **Variantes sobre verde** (`dark-muted`, `dark-line`, `dark-soft`): adaptación tonal de la diapositiva oscura.

**The Apertura y Cierre Rule.** El verde enmarca el relato; las diapositivas intermedias explican sobre marfil.

## Typography

**Display Font:** IBM Plex Sans, embebida localmente como `Plex`, con `system-ui, sans-serif` de respaldo.
**Body Font:** la misma familia; pesos regular y semibold.

### Hierarchy
- **Display:** portada; título fluido y subtítulo regular al 54% de su tamaño.
- **Headline:** título de diapositiva; ancho máximo de 1000px.
- **Title:** nombres de secciones y bloques.
- **Body:** explicación principal; longitud máxima de 70ch, con variantes de 19–23px según la composición.
- **Source:** referencias discretas al pie; permite cortar rutas largas.

Los números de página, métricas y particiones de datos emplean cifras tabulares. En móvil, el cuerpo general baja a 18px y el título de diapositiva se fija en 32px.

## Layout

Contenedor centrado de hasta 1600px, con margen interior de 22px verticales y 40px horizontales. Cada diapositiva usa proporción 16:9 y altura mínima de 680px en escritorio; interior de 46px arriba, 58px a los lados y 48px abajo. Desde 1600px, la altura mínima sube a 780px.

Las composiciones incluyen mitades con separación de 52px, portada de proporción 1.25:0.75, secuencia de cuatro columnas, filas con divisores, ecuación y evidencia de proporción 1.5:1. No hay una retícula única que fuerce todos los argumentos al mismo formato.

Hasta 1000px desaparece la proporción fija y se reduce el interior a 32px. Hasta 650px la lectura se vuelve vertical; las composiciones principales pasan a una columna y la secuencia queda en dos. El diagrama conserva un ancho mínimo de 610px dentro de un área con desplazamiento horizontal. La impresión muestra las 14 diapositivas en páginas horizontales y oculta los controles.

## Elevation & Depth

No se usan sombras. La profundidad se comunica mediante fondos sólidos, contraste tonal, líneas de un píxel y jerarquía tipográfica. Los paneles verdes y los nodos suaves pertenecen al contenido, sin apariencia de tarjeta elevada.

## Shapes

Las diapositivas y paneles son rectangulares. Los controles tienen esquinas discretas; los nodos SVG suavizan sus esquinas. Las divisiones son líneas finas, salvo el borde superior de dos píxeles de los pasos del flujo. La captura conserva su proporción y se encuadra con un borde fino.

## Components

### Controles de presentación

Botones compactos sobre marfil, borde verde grisáceo y altura mínima de 44px. Al pasar el cursor invierten fondo y texto; el estado deshabilitado reduce opacidad al 45%. El foco compartido por botones, enlaces y resumen de notas usa contorno dorado de 3px separado 4px. Flechas, PageUp/PageDown, espacio, Home/End y N complementan los botones sin interceptar controles interactivos.

### Índice

Botones de texto alineados a la izquierda en dos columnas, una en móvil. La diapositiva actual invierte verde y marfil. Su apertura expone el estado accesible y enfoca la entrada actual.

### Notas

Contenedor marfil desplegable bajo la presentación; resumen semibold, cuerpo de 17px y referencia separada. Cada diapositiva conserva además una fuente visible dentro de la lámina.

### Panel de énfasis

Bloque verde con texto marfil y separación interior amplia. En móvil se reduce a 26px. Las filas editoriales y métricas usan divisores, sin marcos de tarjeta.

### Diagramas y evidencia

Arquitectura en SVG nativo con nodos suaves, conexiones verdes y etiquetas Plex. La portada confirma el resultado con un bloque dorado. La captura histórica usa ajuste `contain`, leyenda y atribución explícita; representa evidencia guardada.

### Movimiento

La confirmación de portada se revela mediante recorte durante 0.6s; la barra de progreso escala durante 0.2s. `prefers-reduced-motion: reduce` elimina animaciones y transiciones. No existe avance automático.

## Do's and Don'ts

### Do:
- **Do** conservar fuentes y límites del alcance junto a la explicación.
- **Do** elegir la composición según el argumento y mantener una jerarquía clara.
- **Do** mantener navegación manual, foco visible y alternativa de movimiento reducido.
- **Do** tratar esta guía como propia de la presentación, sin trasladarla automáticamente a la aplicación.

### Don't:
- **Don't** presentar la captura histórica como una sesión en vivo.
- **Don't** sustituir la identidad verde y dorada por la paleta genérica de la consulta inicial.
- **Don't** introducir reproducción automática en una sustentación controlada por quien expone.
