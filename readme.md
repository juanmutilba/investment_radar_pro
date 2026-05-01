# Investment Radar Pro

Aplicación local para analizar un universo de acciones (USA y Argentina), generar un radar con métricas y exportar resultados (Excel/CSV). Incluye API **FastAPI** y panel web **React + Vite**. Los datos de cartera y métricas de scan se guardan en **SQLite**; hay caches y exports en **JSON** y archivos bajo la carpeta de export configurada.

## Requisitos

| Herramienta | Uso |
|-------------|-----|
| **Python** | 3.10 o superior (recomendado 3.11+) |
| **Node.js** | LTS reciente (p. ej. 20.x) |
| **npm** | Viene con Node.js |

En Windows, marcá la opción “Add Python to PATH” al instalar Python.

## Estructura principal

```
investment_radar_pro/
├── api/                 # FastAPI (app principal: api.app:app)
├── webapp/              # Frontend React + Vite
├── core/                # Config, técnicos, scoring, alertas (motor)
├── engines/             # Motores USA / Argentina
├── services/            # Scan, export, cartera, mercado
├── persistence/       # SQLite
├── data/                # Universos, mappings, caches JSON
├── export/              # Lógica de exportación Excel/CSV
├── scripts/             # Scripts de ayuda (arranque Windows)
├── main.py              # Entrada CLI del scan (sin la API)
├── requirements.txt     # Dependencias Python
└── .env                 # Variables opcionales (credenciales, rutas)
```

## Instalación — Backend (Python)

Desde la **raíz del repositorio**:

```bat
python -m venv venv
venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

**Linux/macOS:** `source venv/bin/activate` en lugar de `venv\Scripts\activate`.

## Instalación — Frontend

```bat
cd webapp
npm install
cd ..
```

## Cómo ejecutar — Backend

Con el entorno virtual activado y estando en la raíz del repo:

```bat
python -m uvicorn api.app:app --reload
```

- API: http://127.0.0.1:8000  
- Documentación interactiva: http://127.0.0.1:8000/docs  

## Cómo ejecutar — Frontend

```bat
cd webapp
npm run dev
```

- Panel: http://localhost:5173 (Vite proxy `/api` → backend en el puerto 8000; ver `webapp/vite.config.ts`)

## Arranque rápido en Windows

Desde la raíz del proyecto o haciendo doble clic (el script sube un nivel desde `scripts/`):

```bat
scripts\start_app.bat
```

Crea `venv` si no existe, instala dependencias Python y `npm install` en `webapp` si hace falta, y abre **dos ventanas**: API y Vite.

## Endpoints útiles

| Método | Ruta | Descripción |
|--------|------|-------------|
| GET | `/health` | Comprobación mínima |
| GET | `/docs` | Swagger UI |
| POST | `/run-scan` | Scan completo **síncrono** (puede tardar mucho) |
| POST | `/scan/run` | Inicio de scan en **segundo plano** |
| GET | `/scan/status` | Estado y progreso estimado del scan |
| GET | `/latest-summary` | Resumen del último export |
| GET | `/latest-radar` | Radar USA (último Excel) |
| GET | `/latest-radar-argentina` | Radar Argentina |
| GET | `/latest-alerts` | Alertas del último export |
| GET | `/cedears` | Vista CEDEAR (snapshot / opción `force`) |
| POST | `/events/usa/update` | Actualización en background de cache de eventos USA |
| GET | `/events/usa/update-status` | Estado de esa actualización |
| * | `/portfolio/*` | Cartera (SQLite) |

## Scan desde consola (sin API)

```bat
venv\Scripts\activate
python main.py
```

## Troubleshooting

### “python” no se reconoce / venv no activado

- Instalá Python y reiniciá la terminal, o usá `py -3.11` en lugar de `python`.
- En Windows, activá el venv: `venv\Scripts\activate` (debe aparecer `(venv)` en el prompt).

### `uvicorn` no se encuentra

Instalá dependencias con el venv **activado**:

```bat
pip install -r requirements.txt
```

Usá siempre `python -m uvicorn api.app:app --reload` para no depender del PATH global.

### El frontend falla o no hay `node_modules`

```bat
cd webapp
npm install
```

### Puerto **8000** ocupado

Cerrá el otro proceso que use el puerto o levantá la API en otro puerto:

```bat
python -m uvicorn api.app:app --reload --port 8001
```

Si cambiás el puerto, actualizá el `proxy` en `webapp/vite.config.ts` o la URL base que use el frontend.

### Puerto **5173** ocupado

Vite elegirá otro puerto solo en modo interactivo; o forzá uno:

```bat
cd webapp
npx vite --port 5174
```

### Errores al leer Excel / Yahoo

Comprobá conexión a Internet, que exista la carpeta de export en `core/config` / `.env`, y que `yfinance` pueda alcanzar los servicios de datos.

---

Para reparar solo el entorno Python existente podés usar `repair-venv.bat` en la raíz del repo.
