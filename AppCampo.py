import asyncio, json, sqlite3
from datetime import date
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from nicegui import ui
from shapely.geometry import Point, Polygon

db = sqlite3.connect('campo.db', check_same_thread=False)
db.row_factory = sqlite3.Row
db.executescript('''
CREATE TABLE IF NOT EXISTS lotes(
    id INTEGER PRIMARY KEY,
    nombre TEXT,
    coords TEXT
);
CREATE TABLE IF NOT EXISTS eventos(
    id INTEGER PRIMARY KEY,
    lote_id INTEGER,
    fecha TEXT,
    tipo TEXT,
    cultivo TEXT,
    proposito TEXT,
    obs TEXT
);
CREATE TABLE IF NOT EXISTS animales(
    id INTEGER PRIMARY KEY,
    caravana TEXT UNIQUE,
    categoria TEXT,
    lote_id INTEGER,
    obs TEXT
);
CREATE TABLE IF NOT EXISTS implementos(id INTEGER PRIMARY KEY, nombre TEXT, tipo TEXT,
    marca_modelo TEXT, anio INTEGER, serie TEXT, horas REAL DEFAULT 0, obs TEXT);
CREATE TABLE IF NOT EXISTS servicios(id INTEGER PRIMARY KEY, implemento_id INTEGER,
    fecha TEXT, tipo TEXT, horas REAL, costo REAL, realizado_por TEXT,
    prox_fecha TEXT, prox_horas REAL, obs TEXT);
''')
TIPOS_IMPL = ['tractor', 'sembradora', 'cosechadora', 'pulverizadora', 'arado', 'rastra',
                'acoplado', 'tolva', 'otro']
TIPOS_SERV = ['cambio de aceite', 'engrase', 'filtros', 'reparación', 'revisión general', 'otro']

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

    def eliminar_lote():
        with ui.dialog() as dialog, ui.card():
            ui.label(f"¿Seguro que querés eliminar el lote '{l['nombre']}'?")
            ui.label('Se borrarán también sus eventos asociados.').classes('text-grey')

            def confirmar():
                db.execute('DELETE FROM eventos WHERE lote_id=?', (l['id'],))
                db.execute('UPDATE animales SET lote_id=NULL WHERE lote_id=?', (l['id'],))
                db.execute('DELETE FROM lotes WHERE id=?', (l['id'],))
                db.commit()
                dialog.close()
                sel['lote'] = None
                dibujar_lotes()
                panel_lote.refresh()

            with ui.row():
                ui.button('Cancelar', on_click=dialog.close)
                ui.button('Eliminar', on_click=confirmar).classes('bg-red-500 text-white')
        dialog.open()

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
    with ui.row():
        ui.button('Registrar', on_click=guardar)
        ui.button('Eliminar lote', on_click=eliminar_lote).classes('bg-red-500 text-white')

    rows = [dict(r) for r in db.execute(
        'SELECT id,fecha,tipo,cultivo,proposito,obs FROM eventos WHERE lote_id=? '
        'ORDER BY fecha DESC, id DESC', (l['id'],))]
    tabla_eventos = ui.table(rows=rows, row_key='id', selection='single',
        columns=[{'name': k, 'label': k, 'field': k}
                 for k in ['fecha', 'tipo', 'cultivo', 'proposito', 'obs']]).classes('w-full')

    def eliminar_evento():
        if not tabla_eventos.selected:
            ui.notify('Seleccioná el registro que querés eliminar', type='warning')
            return
        evento = tabla_eventos.selected[0]
        with ui.dialog() as dialog, ui.card():
            ui.label(f"¿Eliminar el registro del {evento['fecha']} ({evento['tipo']})?")
            with ui.row():
                ui.button('Cancelar', on_click=dialog.close)

                def confirmar():
                    db.execute('DELETE FROM eventos WHERE id=? AND lote_id=?',
                               (evento['id'], l['id']))
                    db.commit()
                    dialog.close()
                    panel_lote.refresh()

                ui.button('Eliminar', on_click=confirmar).classes('bg-red-500 text-white')
        dialog.open()

    ui.button('Eliminar registro seleccionado', on_click=eliminar_evento).classes(
        'bg-red-500 text-white')

# ---------- ANIMALES ----------
sel_animal = {'id': None}

def opciones_animales():
    return {r['id']: f"{r['caravana']} · {r['categoria']}"
            for r in db.execute('SELECT id,caravana,categoria FROM animales ORDER BY caravana')}

@ui.refreshable
def tabla_animales():
    rows = [dict(r) for r in db.execute(
        'SELECT a.caravana, a.categoria, l.nombre AS lote, a.obs FROM animales a '
        'LEFT JOIN lotes l ON l.id=a.lote_id ORDER BY a.caravana')]
    ui.table(rows=rows, columns=[{'name': k, 'label': k, 'field': k}
             for k in ['caravana', 'categoria', 'lote', 'obs']]).classes('w-full')

@ui.refreshable
def detalle_animal():
    if sel_animal['id'] is None:
        ui.label('Elegí un animal para ver el detalle').classes('text-grey')
        return
    a = db.execute('SELECT a.*, l.nombre AS lote FROM animales a '
                   'LEFT JOIN lotes l ON l.id=a.lote_id WHERE a.id=?',
                   (sel_animal['id'],)).fetchone()
    if a is None:
        return
    with ui.card().classes('w-full'):
        ui.label(f"Caravana: {a['caravana']}").classes('text-subtitle1')
        ui.label(f"Categoría: {a['categoria'] or '-'}")
        ui.label(f"Lote actual: {a['lote'] or '-'}")
        ui.label(f"Obs: {a['obs'] or '-'}")

def elegir_animal(e):
    sel_animal['id'] = e.value
    detalle_animal.refresh()

def refrescar_animales():
    selector.set_options(opciones_animales())
    tabla_animales.refresh()
    detalle_animal.refresh()

@ui.refreshable
def form_animales():
    caravana = ui.input('Caravana')
    cat = ui.select(CATEGORIAS, label='Categoría', value=CATEGORIAS[0])
    lotes = {r['id']: r['nombre'] for r in db.execute('SELECT id,nombre FROM lotes')}
    lote = ui.select(lotes, label='Lote actual (opcional)', clearable=True)
    obs = ui.textarea('Observaciones')
    def guardar():
        if not caravana.value:
            ui.notify('Falta la caravana', type='warning'); return
        try:
            db.execute('INSERT INTO animales(caravana,categoria,lote_id,obs) VALUES(?,?,?,?)',
                       (caravana.value, cat.value, lote.value, obs.value))
            db.commit()
        except sqlite3.IntegrityError:
            ui.notify('Esa caravana ya existe', type='negative'); return
        form_animales.refresh()      # limpia los campos
        refrescar_animales()
    ui.button('Agregar', on_click=guardar)

# ---------- IMPLEMENTOS ----------
sel_impl = {'id': None}

def opciones_impl():
    return {r['id']: r['nombre'] for r in db.execute('SELECT id,nombre FROM implementos ORDER BY nombre')}

def estado_servicio(imp):
    """Devuelve (último servicio, lista de motivos de vencimiento)."""
    ult = db.execute('SELECT * FROM servicios WHERE implemento_id=? '
                     'ORDER BY fecha DESC, id DESC LIMIT 1', (imp['id'],)).fetchone()
    if ult is None:
        return None, []
    motivos = []
    if ult['prox_fecha'] and ult['prox_fecha'] < date.today().isoformat():
        motivos.append('fecha vencida')
    if ult['prox_horas'] and (imp['horas'] or 0) >= ult['prox_horas']:
        motivos.append('horas alcanzadas')
    return ult, motivos

@ui.refreshable
def vencimientos():
    filas = []
    for imp in db.execute('SELECT * FROM implementos'):
        ult, motivos = estado_servicio(imp)
        if motivos:
            filas.append({'implemento': imp['nombre'], 'motivo': ', '.join(motivos),
                          'prox_fecha': ult['prox_fecha'] or '-',
                          'prox_horas': ult['prox_horas'] or '-', 'horas': imp['horas']})
    if not filas:
        ui.label('Sin servicios vencidos').classes('text-positive'); return
    ui.table(rows=filas, columns=[{'name': k, 'label': k, 'field': k}
             for k in ['implemento', 'motivo', 'prox_fecha', 'prox_horas', 'horas']]).classes('w-full')

@ui.refreshable
def form_impl():
    with ui.expansion('Nuevo implemento', icon='add').classes('w-full'):
        nombre = ui.input('Nombre (ej: Tractor JD 5705)')
        marca = ui.input('Marca / modelo')
        anio = ui.number('Año', format='%.0f')
        serie = ui.input('N° de serie / chasis')
        horas = ui.number('Horas actuales (horómetro)', value=0)
        obs = ui.textarea('Observaciones')
        def guardar():
            if not nombre.value:
                ui.notify('Falta el nombre', type='warning'); return
            db.execute('INSERT INTO implementos(nombre,tipo,marca_modelo,anio,serie,horas,obs) '
                       'VALUES(?,?,?,?,?,?,?)',
                       (nombre.value, '', marca.value,
                        int(anio.value) if anio.value else None,
                        serie.value, horas.value or 0, obs.value))
            db.commit()
            form_impl.refresh()
            selector_impl.set_options(opciones_impl())
            vencimientos.refresh()
        ui.button('Guardar implemento', on_click=guardar)

@ui.refreshable
def panel_impl():
    if sel_impl['id'] is None:
        ui.label('Elegí un implemento').classes('text-grey'); return
    imp = db.execute('SELECT * FROM implementos WHERE id=?', (sel_impl['id'],)).fetchone()
    if imp is None:
        return
    ult, motivos = estado_servicio(imp)

    with ui.card().classes('w-full'):
        ui.label(f"{imp['nombre']} ({imp['tipo']})").classes('text-h6')
        ui.label(f"{imp['marca_modelo'] or '-'} · año {imp['anio'] or '-'} · serie {imp['serie'] or '-'}")
        ui.label(f"Horas actuales: {imp['horas'] or 0}")
        if ult is None:
            ui.label('Sin servicios registrados').classes('text-grey')
        else:
            ui.label(f"Último servicio: {ult['fecha']} ({ult['tipo']})")
            color = 'text-negative' if motivos else 'text-positive'
            ui.label(f"Próximo: {ult['prox_fecha'] or '-'} / {ult['prox_horas'] or '-'} hs"
                     + (f"  ⚠ {', '.join(motivos)}" if motivos else '')).classes(color)

    ui.label('Registrar servicio').classes('text-subtitle1')
    fecha = ui.input('Fecha del servicio', value=date.today().isoformat()).props('type=date')
    tipo = ui.select(TIPOS_SERV, label='Tipo de servicio', value=TIPOS_SERV[0])
    horas = ui.number('Horas del implemento al momento del servicio')
    costo = ui.number('Costo (opcional)')
    quien = ui.input('Realizado por')
    pf = ui.input('Próximo servicio (fecha)').props('type=date')
    ph = ui.number('Próximo servicio (a las X horas)')
    obs = ui.textarea('Observaciones')

    def guardar():
        db.execute('INSERT INTO servicios(implemento_id,fecha,tipo,horas,costo,realizado_por,'
                   'prox_fecha,prox_horas,obs) VALUES(?,?,?,?,?,?,?,?,?)',
                   (imp['id'], fecha.value, tipo.value, horas.value, costo.value, quien.value,
                    pf.value, ph.value, obs.value))
        if horas.value and horas.value > (imp['horas'] or 0):
            db.execute('UPDATE implementos SET horas=? WHERE id=?', (horas.value, imp['id']))
        db.commit()
        panel_impl.refresh(); vencimientos.refresh()
    ui.button('Registrar servicio', on_click=guardar)

    rows = [dict(r) for r in db.execute(
        'SELECT fecha,tipo,horas,costo,realizado_por,prox_fecha,prox_horas,obs '
        'FROM servicios WHERE implemento_id=? ORDER BY fecha DESC, id DESC', (imp['id'],))]
    ui.table(rows=rows, columns=[{'name': k, 'label': k, 'field': k} for k in
             ['fecha', 'tipo', 'horas', 'costo', 'realizado_por', 'prox_fecha', 'prox_horas', 'obs']]
             ).classes('w-full')

def elegir_impl(e):
    sel_impl['id'] = e.value
    panel_impl.refresh()

# ---------- UI ----------
with ui.tabs() as tabs:
    t1 = ui.tab('Lotes'); t2 = ui.tab('Animales'); t3 = ui.tab('Implementos')
with ui.tab_panels(tabs, value=t1).classes('w-full'):
    with ui.tab_panel(t1):
        with ui.row().classes('w-full items-end'):
            localidad = ui.input('Pueblo / ciudad').props('clearable')

            async def buscar_localidad():
                consulta = (localidad.value or '').strip()
                if not consulta:
                    ui.notify('Ingresá un pueblo o ciudad', type='warning')
                    return

                url = 'https://nominatim.openstreetmap.org/search?' + urlencode({
                    'q': consulta,
                    'countrycodes': 'ar',
                    'format': 'jsonv2',
                    'limit': 1,
                })
                solicitud = Request(url, headers={'User-Agent': 'AppCampo/1.0'})

                try:
                    def consultar():
                        with urlopen(solicitud, timeout=10) as respuesta:
                            return json.load(respuesta)

                    resultados = await asyncio.to_thread(consultar)
                except (URLError, TimeoutError, json.JSONDecodeError):
                    ui.notify('No se pudo buscar la localidad. Revisá la conexión.',
                              type='negative')
                    return

                if not resultados:
                    ui.notify('No se encontró esa localidad en Argentina', type='warning')
                    return

                resultado = resultados[0]
                mapa.set_center((float(resultado['lat']), float(resultado['lon'])))
                mapa.set_zoom(13)
                ui.notify(f"Mapa centrado en {resultado['display_name']}", type='positive')

            ui.button('Buscar en el mapa', on_click=buscar_localidad, icon='search')
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
        with ui.row().classes('w-full no-wrap'):
            with ui.column().classes('w-1/3'):
                form_animales()
            with ui.column().classes('w-2/3'):       # lateral derecho
                ui.label('Animales registrados').classes('text-h6')
                selector = ui.select(opciones_animales(), label='Ver animal',
                                    clearable=True, with_input=True,
                                    on_change=elegir_animal).classes('w-full')
                detalle_animal()
                tabla_animales()

    with ui.tab_panel(t3):
        with ui.row().classes('w-full no-wrap'):
            with ui.column().classes('w-1/3'):
                form_impl()
                selector_impl = ui.select(opciones_impl(), label='Implemento',
                                          with_input=True, clearable=True,
                                          on_change=elegir_impl).classes('w-full')
            with ui.column().classes('w-2/3'):
                vencimientos()
                panel_impl()

dibujar_lotes()
ui.run(title='Campo')