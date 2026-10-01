import json, sqlite3
from datetime import date
from nicegui import ui
from shapely.geometry import Point, Polygon

db = sqlite3.connect('campo.db', check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE IF NOT EXISTS lotes(id INTEGER PRIMARY KEY, nombre TEXT, coords TEXT);
CREATE TABLE IF NOT EXISTS eventos(id INTEGER PRIMARY KEY, lote_id INTEGER, fecha TEXT,
    tipo TEXT, cultivo TEXT, proposito TEXT, obs TEXT);
CREATE TABLE IF NOT EXISTS animales(id INTEGER PRIMARY KEY, caravana TEXT UNIQUE,
    categoria TEXT, lote_id INTEGER, obs TEXT);
''')

sel = {'lote': None}     # lote seleccionado
capas = []               # polígonos dibujados (para poder redibujar)

TIPOS = ['siembra', 'arada', 'cosecha', 'pastoreo', 'otro']
PROPOSITOS = ['grano', 'forraje', 'cobertura', 'pastoreo directo', 'otro']
CATEGORIAS = ['vaca', 'vaquillona', 'ternero', 'novillo', 'toro', 'otro']

# ---------- MAPA ----------
def dibujar_lotes():
    for c in capas:
        mapa.remove_layer(c)
    capas.clear()
    for l in db.execute('SELECT * FROM lotes'):
        color = 'yellow' if sel['lote'] == l['id'] else 'lime'
        capas.append(mapa.generic_layer(name='polygon',
                     args=[json.loads(l['coords']), {'color': color, 'weight': 2}]))

def al_click(e):
    p = Point(e.args['latlng']['lng'], e.args['latlng']['lat'])
    for l in db.execute('SELECT * FROM lotes'):
        poly = Polygon([(lng, lat) for lat, lng in json.loads(l['coords'])])
        if poly.contains(p):
            sel['lote'] = l['id']
            dibujar_lotes(); panel_lote.refresh()
            return

def al_dibujar(e):
    anillo = e.args['layer']['_latlngs'][0]
    coords = [[p['lat'], p['lng']] for p in anillo]
    with ui.dialog() as d, ui.card():
        nombre = ui.input('Nombre del lote')
        def guardar():
            db.execute('INSERT INTO lotes(nombre, coords) VALUES(?,?)',
                       (nombre.value, json.dumps(coords)))
            db.commit(); d.close(); dibujar_lotes()
        ui.button('Guardar', on_click=guardar)
    d.open()

# ---------- PANEL DEL LOTE ----------
@ui.refreshable
def panel_lote():
    if sel['lote'] is None:
        ui.label('Hacé click en un lote del mapa'); return
    l = db.execute('SELECT * FROM lotes WHERE id=?', (sel['lote'],)).fetchone()
    ui.label(f"Lote: {l['nombre']}").classes('text-h6')

    tipo = ui.select(TIPOS, label='Acción', value='siembra')
    fecha = ui.input('Fecha', value=date.today().isoformat()).props('type=date')
    cultivo = ui.input('Cultivo / pasto')
    prop = ui.select(PROPOSITOS, label='Propósito')
    obs = ui.textarea('Observaciones')

    def guardar():
        db.execute('INSERT INTO eventos(lote_id,fecha,tipo,cultivo,proposito,obs) '
                   'VALUES(?,?,?,?,?,?)',
                   (l['id'], fecha.value, tipo.value, cultivo.value, prop.value, obs.value))
        db.commit(); panel_lote.refresh()
    ui.button('Registrar', on_click=guardar)

    rows = [dict(r) for r in db.execute(
        'SELECT fecha,tipo,cultivo,proposito,obs FROM eventos WHERE lote_id=? '
        'ORDER BY fecha DESC', (l['id'],))]
    ui.table(rows=rows, columns=[{'name': k, 'label': k, 'field': k}
             for k in ['fecha', 'tipo', 'cultivo', 'proposito', 'obs']])

# ---------- ANIMALES ----------
@ui.refreshable
def tabla_animales():
    rows = [dict(r) for r in db.execute(
        'SELECT a.caravana, a.categoria, l.nombre AS lote, a.obs FROM animales a '
        'LEFT JOIN lotes l ON l.id=a.lote_id')]
    ui.table(rows=rows, columns=[{'name': k, 'label': k, 'field': k}
             for k in ['caravana', 'categoria', 'lote', 'obs']])

def form_animales():
    caravana = ui.input('Caravana')
    cat = ui.select(CATEGORIAS, label='Categoría')
    lotes = {r['id']: r['nombre'] for r in db.execute('SELECT id,nombre FROM lotes')}
    lote = ui.select(lotes, label='Lote actual (opcional)', clearable=True)
    obs = ui.textarea('Observaciones')
    def guardar():
        try:
            db.execute('INSERT INTO animales(caravana,categoria,lote_id,obs) VALUES(?,?,?,?)',
                       (caravana.value, cat.value, lote.value, obs.value))
            db.commit(); tabla_animales.refresh()
        except sqlite3.IntegrityError:
            ui.notify('Esa caravana ya existe', type='negative')
    ui.button('Agregar', on_click=guardar)

# ---------- UI ----------
with ui.tabs() as tabs:
    t1 = ui.tab('Lotes'); t2 = ui.tab('Animales')
with ui.tab_panels(tabs, value=t1).classes('w-full'):
    with ui.tab_panel(t1):
        with ui.row().classes('w-full no-wrap'):
            mapa = ui.leaflet(center=(-35.66, -63.75), zoom=13,
                draw_control={'draw': {'polygon': True, 'marker': False, 'circle': False,
                    'rectangle': False, 'polyline': False, 'circlemarker': False},
                    'edit': {'edit': False, 'remove': False}}).classes('w-2/3').style('height:80vh')
            mapa.tile_layer(url_template='https://server.arcgisonline.com/ArcGIS/rest/services/'
                            'World_Imagery/MapServer/tile/{z}/{y}/{x}', options={'maxZoom': 19})
            mapa.on('map-click', al_click)
            mapa.on('draw:created', al_dibujar)
            with ui.column().classes('w-1/3'):
                panel_lote()
    with ui.tab_panel(t2):
        form_animales(); tabla_animales()

dibujar_lotes()
ui.run(title='Campo')