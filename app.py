"""
NeoPark ECCI — Tercera Entrega (Sistema Completo)
Temas cubiertos:
  - Consultas avanzadas con JOINs y subconsultas
  - Seguridad: roles, hashing, sesiones, CSRF básico
  - PL/SQL equivalente: funciones y procedimientos en Python
  - Transacciones explícitas con BEGIN/COMMIT/ROLLBACK
  - Concurrencia: threading.Lock para acceso atómico a BD
  - Triggers equivalentes: validaciones antes/después de cada operación
  - Vistas: consultas reutilizables encapsuladas
Integrantes: Justin Infante · Jhon Guzmán · Alejandro Jiménez
"""

from flask import (Flask, render_template, request, redirect,
                   url_for, flash, session, jsonify, Response)
from datetime import datetime
from functools import wraps
import sqlite3, os, hashlib, math, csv, io, json, threading

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'neopark-ecci-2026-pro')

# ── Ruta de BD compatible con Render/Railway (variable de entorno) ────────────
DB_PATH = os.environ.get('DB_PATH',
          os.path.join(os.path.dirname(__file__), 'instance', 'neopark.db'))

# ── CONCURRENCIA: Lock global para operaciones críticas de check-in/out ───────
# Garantiza que dos peticiones simultáneas no asignen el mismo espacio
_db_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1: INICIALIZACIÓN DE BD (esquema + datos)
# ═══════════════════════════════════════════════════════════════════════════════
def get_db():
    db = sqlite3.connect(DB_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.execute("PRAGMA journal_mode = WAL")   # Write-Ahead Logging: mejor concurrencia
    return db

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    db = get_db()
    # TRANSACCIÓN de creación de esquema
    db.executescript("""
        CREATE TABLE IF NOT EXISTS ROL (
            id_rol INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_rol TEXT NOT NULL UNIQUE,
            descripcion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS TIPO_VEHICULO (
            id_tipo INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre_tipo TEXT NOT NULL UNIQUE, descripcion TEXT);
        CREATE TABLE IF NOT EXISTS USUARIO (
            id_usuario INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL, apellido TEXT NOT NULL,
            correo TEXT NOT NULL UNIQUE, contrasena_hash TEXT NOT NULL,
            id_rol INTEGER NOT NULL DEFAULT 3, activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (id_rol) REFERENCES ROL(id_rol) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS VEHICULO (
            placa TEXT PRIMARY KEY, id_tipo INTEGER NOT NULL,
            marca TEXT, modelo TEXT, color TEXT, id_usuario INTEGER NOT NULL,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT,
            FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS ESPACIO (
            id_espacio INTEGER PRIMARY KEY AUTOINCREMENT,
            codigo TEXT NOT NULL UNIQUE, id_tipo INTEGER NOT NULL,
            disponible INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS TARIFA (
            id_tarifa INTEGER PRIMARY KEY AUTOINCREMENT, id_tipo INTEGER NOT NULL,
            valor_por_hora REAL NOT NULL, fraccion_minutos INTEGER NOT NULL DEFAULT 15,
            activo INTEGER NOT NULL DEFAULT 1, fecha_vigencia TEXT NOT NULL,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT,
            CHECK (valor_por_hora > 0), CHECK (fraccion_minutos > 0));
        CREATE TABLE IF NOT EXISTS REGISTRO_PARQUEO (
            id_registro INTEGER PRIMARY KEY AUTOINCREMENT,
            placa TEXT NOT NULL, id_espacio INTEGER NOT NULL,
            fecha_entrada TEXT NOT NULL, hora_entrada TEXT NOT NULL,
            fecha_salida TEXT, hora_salida TEXT,
            valor_pagado REAL, estado TEXT NOT NULL DEFAULT 'Abierto'
                CHECK(estado IN ('Abierto','Cerrado')),
            FOREIGN KEY (placa) REFERENCES VEHICULO(placa) ON DELETE RESTRICT,
            FOREIGN KEY (id_espacio) REFERENCES ESPACIO(id_espacio) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS AUDITORIA (
            id_auditoria INTEGER PRIMARY KEY AUTOINCREMENT,
            id_usuario INTEGER NOT NULL, accion TEXT NOT NULL,
            detalle TEXT, ip TEXT,
            fecha_hora TEXT NOT NULL DEFAULT (datetime('now','localtime')),
            FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario) ON DELETE RESTRICT);
    """)
    if not db.execute("SELECT 1 FROM ROL LIMIT 1").fetchone():
        _seed_data(db)
    db.commit(); db.close()

def _seed_data(db):
    def pw(p): return hashlib.sha256(p.encode()).hexdigest()
    db.executescript("""
        INSERT INTO ROL VALUES(1,'Administrador','Acceso total al sistema'),
            (2,'Operario','Registro de entradas y salidas'),
            (3,'Usuario','Consulta e historial personal'),
            (4,'Auditor','Solo lectura'),
            (5,'Supervisor','Supervisión y reportes');
        INSERT INTO TIPO_VEHICULO VALUES
            (1,'Carro','Automóvil de cuatro ruedas'),
            (2,'Moto','Motocicleta de dos ruedas'),
            (3,'Bicicleta','Vehículo no motorizado'),
            (4,'Camioneta','Vehículo de carga liviana'),
            (5,'Patineta','Movilidad personal no motorizada');
        INSERT INTO ESPACIO(codigo,id_tipo,disponible) VALUES
            ('C-01',1,0),('C-02',1,1),('C-03',1,1),('C-04',1,1),('C-05',1,1),
            ('C-06',1,1),('C-07',1,1),('C-08',1,1),('C-09',1,1),('C-10',1,1),
            ('M-01',2,0),('M-02',2,1),('M-03',2,1),('M-04',2,1),('M-05',2,1),
            ('M-06',2,1),('M-07',2,1),('M-08',2,1),
            ('B-01',3,1),('B-02',3,1),('B-03',3,1),('B-04',3,1),('B-05',3,1);
        INSERT INTO TARIFA(id_tipo,valor_por_hora,fraccion_minutos,activo,fecha_vigencia) VALUES
            (1,3000,15,1,'2026-01-01'),(2,2000,15,1,'2026-01-01'),
            (3,500,60,1,'2026-01-01'),(1,3500,15,0,'2025-01-01'),
            (2,2500,15,0,'2025-01-01');
    """)
    a=pw("Admin123!"); b=pw("Op123!"); c=pw("User123!")
    for row in [('Justin','Infante','justisfe.infantecristancho@ecci.edu.co',a,1),
                ('Jhon','Guzmán','jhone.guzmansalinas@ecci.edu.co',b,2),
                ('Alejandro','Jiménez','alejoe.jimenezperez@ecci.edu.co',c,3),
                ('Carlos','Rodríguez','c.rodriguez@ecci.edu.co',c,3),
                ('María','López','m.lopez@ecci.edu.co',c,3)]:
        db.execute("INSERT INTO USUARIO(nombre,apellido,correo,contrasena_hash,id_rol) VALUES(?,?,?,?,?)",row)
    db.executescript("""
        INSERT INTO VEHICULO VALUES
            ('ABC123',1,'Chevrolet','Spark','Blanco',3),
            ('XYZ789',2,'Honda','CBR150','Negro',4),
            ('QWE456',1,'Renault','Logan','Gris',5),
            ('MNO321',3,NULL,NULL,'Azul',3),
            ('PQR654',2,'Yamaha','FZ16','Rojo',5);
        INSERT INTO REGISTRO_PARQUEO(placa,id_espacio,fecha_entrada,hora_entrada,fecha_salida,hora_salida,valor_pagado,estado) VALUES
            ('QWE456',2,'2026-05-18','09:00:00','2026-05-18','12:00:00',9000,'Cerrado'),
            ('MNO321',7,'2026-05-17','07:15:00','2026-05-17','17:00:00',5000,'Cerrado'),
            ('PQR654',5,'2026-05-16','10:00:00','2026-05-16','11:30:00',3000,'Cerrado'),
            ('XYZ789',4,'2026-05-15','08:00:00','2026-05-15','10:00:00',4000,'Cerrado'),
            ('ABC123',1,'2026-05-14','07:30:00','2026-05-14','18:00:00',15000,'Cerrado');
        INSERT INTO REGISTRO_PARQUEO(placa,id_espacio,fecha_entrada,hora_entrada,estado) VALUES
            ('ABC123',1,date('now'),time('now'),'Abierto'),
            ('XYZ789',4,date('now'),time('now'),'Abierto');
        UPDATE ESPACIO SET disponible=0 WHERE id_espacio IN (1,4);
    """)

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2: FUNCIONES EQUIVALENTES A PL/SQL
# ═══════════════════════════════════════════════════════════════════════════════

def fn_calcular_cobro(db, id_tipo, dt_entrada, dt_salida):
    """Función equivalente a fn_calcular_cobro() de MySQL."""
    tarifa = db.execute(
        "SELECT valor_por_hora, fraccion_minutos FROM TARIFA "
        "WHERE id_tipo=? AND activo=1 ORDER BY fecha_vigencia DESC LIMIT 1",
        (id_tipo,)
    ).fetchone()
    if not tarifa: return 0
    minutos = max(0, (dt_salida - dt_entrada).total_seconds() / 60)
    fracciones = math.ceil(minutos / tarifa['fraccion_minutos']) if minutos > 0 else 0
    return round(fracciones * (tarifa['valor_por_hora'] / (60 / tarifa['fraccion_minutos'])), 0)

def fn_estado_parqueadero(db, id_tipo):
    """Función equivalente a fn_estado_parqueadero() de MySQL."""
    libres = db.execute(
        "SELECT COUNT(*) FROM ESPACIO WHERE id_tipo=? AND disponible=1", (id_tipo,)
    ).fetchone()[0]
    if libres == 0:   return 'OCUPACION_TOTAL'
    if libres <= 2:   return 'CASI_LLENO'
    return 'DISPONIBLE'

def fn_usuario_tiene_activo(db, id_usuario):
    """Función equivalente a fn_usuario_tiene_activo() de MySQL."""
    count = db.execute(
        "SELECT COUNT(*) FROM REGISTRO_PARQUEO r "
        "JOIN VEHICULO v ON r.placa=v.placa "
        "WHERE v.id_usuario=? AND r.estado='Abierto'", (id_usuario,)
    ).fetchone()[0]
    return count > 0

def fn_minutos_transcurridos(dt_entrada):
    """Minutos desde dt_entrada hasta ahora."""
    return max(0, int((datetime.now() - dt_entrada).total_seconds() / 60))

def duracion_str(dt_e, dt_s=None):
    if dt_s is None: dt_s = datetime.now()
    delta = dt_s - dt_e
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"{h}h {m}min"

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3: PROCEDIMIENTOS EQUIVALENTES A PL/SQL
# Cada sp_xxx implementa el mismo lógico del stored procedure MySQL,
# con TRANSACCIÓN explícita y manejo de errores.
# ═══════════════════════════════════════════════════════════════════════════════

def sp_checkin(placa, id_usuario):
    """
    Procedimiento equivalente a sp_checkin() MySQL.
    Usa _db_lock para garantizar atomicidad (control de concurrencia).
    Devuelve (ok: bool, mensaje: str, espacio: str|None)
    """
    with _db_lock:                          # CONTROL DE CONCURRENCIA
        db = get_db()
        try:
            db.execute("BEGIN")             # INICIO DE TRANSACCIÓN

            # TRIGGER equivalente: validar RN1 — vehículo registrado
            veh = db.execute(
                "SELECT v.*, tv.nombre_tipo FROM VEHICULO v "
                "JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=?",
                (placa,)
            ).fetchone()
            if not veh:
                db.execute("ROLLBACK")
                return False, 'ERROR RN1: Vehículo no registrado en el sistema', None

            # TRIGGER equivalente: validar RN2 — un activo por usuario
            if fn_usuario_tiene_activo(db, veh['id_usuario']):
                db.execute("ROLLBACK")
                return False, 'ERROR RN2: El propietario ya tiene un vehículo dentro', None

            # TRIGGER equivalente: validar RN4 — ocupación total
            espacio = db.execute(
                "SELECT * FROM ESPACIO WHERE id_tipo=? AND disponible=1 LIMIT 1",
                (veh['id_tipo'],)
            ).fetchone()
            if not espacio:
                estado = fn_estado_parqueadero(db, veh['id_tipo'])
                db.execute("ROLLBACK")
                return False, f'ERROR RN4: {estado} — Sin espacios para {veh["nombre_tipo"]}', None

            now = datetime.now()
            db.execute(
                "INSERT INTO REGISTRO_PARQUEO(placa,id_espacio,fecha_entrada,hora_entrada,estado) "
                "VALUES(?,?,?,?,'Abierto')",
                (placa, espacio['id_espacio'], now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'))
            )
            # TRIGGER equivalente: marcar espacio ocupado
            db.execute("UPDATE ESPACIO SET disponible=0 WHERE id_espacio=?", (espacio['id_espacio'],))

            _log(db, 'CHECKIN', f'Placa:{placa} → Espacio:{espacio["codigo"]}')
            db.execute("COMMIT")            # CONFIRMAR TRANSACCIÓN
            return True, f'Check-in exitoso — Espacio asignado: {espacio["codigo"]}', espacio['codigo']

        except Exception as e:
            db.execute("ROLLBACK")          # REVERTIR en caso de error
            return False, f'ERROR inesperado: {str(e)}', None
        finally:
            db.close()

def sp_checkout(id_registro):
    """
    Procedimiento equivalente a sp_checkout() MySQL.
    Usa _db_lock y transacción explícita.
    Devuelve (ok, mensaje, ticket_dict | None)
    """
    with _db_lock:                          # CONTROL DE CONCURRENCIA
        db = get_db()
        try:
            db.execute("BEGIN")             # INICIO DE TRANSACCIÓN

            reg = db.execute(
                "SELECT * FROM REGISTRO_PARQUEO WHERE id_registro=? AND estado='Abierto'",
                (id_registro,)
            ).fetchone()
            if not reg:
                db.execute("ROLLBACK")
                return False, 'Registro no encontrado o ya cerrado', None

            veh = db.execute(
                "SELECT v.*,tv.nombre_tipo FROM VEHICULO v "
                "JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=?",
                (reg['placa'],)
            ).fetchone()
            prop = db.execute(
                "SELECT nombre||' '||apellido as nombre FROM USUARIO WHERE id_usuario=?",
                (veh['id_usuario'],)
            ).fetchone()
            esp = db.execute(
                "SELECT codigo FROM ESPACIO WHERE id_espacio=?", (reg['id_espacio'],)
            ).fetchone()

            dt_e = datetime.strptime(f"{reg['fecha_entrada']} {reg['hora_entrada']}", '%Y-%m-%d %H:%M:%S')
            dt_s = datetime.now()

            # TRIGGER equivalente: validar que salida > entrada
            if dt_s <= dt_e:
                db.execute("ROLLBACK")
                return False, 'La hora de salida debe ser posterior a la entrada', None

            valor = fn_calcular_cobro(db, veh['id_tipo'], dt_e, dt_s)
            dur   = duracion_str(dt_e, dt_s)

            db.execute(
                "UPDATE REGISTRO_PARQUEO SET fecha_salida=?,hora_salida=?,valor_pagado=?,estado='Cerrado' "
                "WHERE id_registro=?",
                (dt_s.strftime('%Y-%m-%d'), dt_s.strftime('%H:%M:%S'), valor, id_registro)
            )
            # TRIGGER equivalente: liberar espacio
            db.execute("UPDATE ESPACIO SET disponible=1 WHERE id_espacio=?", (reg['id_espacio'],))

            ticket = {
                'id_registro': id_registro, 'placa': reg['placa'],
                'tipo': veh['nombre_tipo'], 'espacio': esp['codigo'],
                'propietario': prop['nombre'],
                'entrada': f"{reg['fecha_entrada']} {reg['hora_entrada'][:5]}",
                'salida': dt_s.strftime('%Y-%m-%d %H:%M'),
                'duracion': dur, 'valor': int(valor),
            }
            _log(db, 'CHECKOUT', f'Placa:{reg["placa"]},Valor:${int(valor):,},Dur:{dur}')
            db.execute("COMMIT")            # CONFIRMAR TRANSACCIÓN
            # Guardar en sesión para mostrar notificación en dashboard de usuario
            if 'user_id' in session:
                session['recien_salio'] = {
                    'placa': reg['placa'], 'espacio': esp['codigo'],
                    'duracion': dur, 'valor': int(valor)
                }
            return True, f'Check-out completado. Valor: ${int(valor):,}', ticket

        except Exception as e:
            db.execute("ROLLBACK")          # REVERTIR en caso de error
            return False, f'ERROR: {str(e)}', None
        finally:
            db.close()

def sp_actualizar_tarifa(id_tipo, valor_hora, fraccion):
    """Procedimiento equivalente a sp_actualizar_tarifa() MySQL."""
    if valor_hora <= 0:
        return False, 'El valor por hora debe ser mayor a 0'
    db = get_db()
    try:
        db.execute("BEGIN")
        db.execute("UPDATE TARIFA SET activo=0 WHERE id_tipo=?", (id_tipo,))
        db.execute(
            "INSERT INTO TARIFA(id_tipo,valor_por_hora,fraccion_minutos,activo,fecha_vigencia) "
            "VALUES(?,?,?,1,date('now'))", (id_tipo, valor_hora, fraccion)
        )
        _log(db, 'TARIFA_ACTUALIZADA', f'Tipo:{id_tipo},Valor:${valor_hora:,.0f}')
        db.execute("COMMIT")
        return True, f'Tarifa actualizada a ${valor_hora:,.0f}/hora'
    except Exception as e:
        db.execute("ROLLBACK")
        return False, f'ERROR: {str(e)}'
    finally:
        db.close()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4: VISTAS EQUIVALENTES (funciones que encapsulan consultas)
# ═══════════════════════════════════════════════════════════════════════════════

def view_ocupacion_actual(db):
    """Equivalente a V_OCUPACION_ACTUAL de MySQL."""
    return db.execute("""
        SELECT e.id_espacio, e.codigo, tv.nombre_tipo,
               CASE WHEN e.disponible=1 THEN 'Libre' ELSE 'Ocupado' END as estado,
               e.disponible,
               r.placa, r.fecha_entrada, r.hora_entrada,
               u.nombre||' '||u.apellido as propietario,
               CAST((julianday('now') - julianday(r.fecha_entrada||' '||r.hora_entrada))*24*60 AS INTEGER) as minutos_transcurridos,
               CASE WHEN e.disponible=1 THEN 'Libre' ELSE 'Ocupado' END as estado_texto
        FROM ESPACIO e
        JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo
        LEFT JOIN REGISTRO_PARQUEO r ON r.id_espacio=e.id_espacio AND r.estado='Abierto'
        LEFT JOIN VEHICULO v ON r.placa=v.placa
        LEFT JOIN USUARIO u ON v.id_usuario=u.id_usuario
        ORDER BY e.codigo
    """).fetchall()

def view_disponibilidad_tipo(db):
    """Equivalente a V_DISPONIBILIDAD_TIPO de MySQL."""
    return db.execute("""
        SELECT tv.nombre_tipo,
               COUNT(e.id_espacio) as total_espacios,
               SUM(e.disponible) as espacios_libres,
               SUM(1-e.disponible) as espacios_ocupados,
               ROUND(CAST(SUM(1-e.disponible) AS REAL)/COUNT(e.id_espacio)*100,1) as porcentaje_ocupacion
        FROM ESPACIO e JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo
        GROUP BY tv.id_tipo, tv.nombre_tipo
    """).fetchall()

def view_recaudo_tipo(db, filtro_sql):
    """Equivalente a V_RECAUDO_POR_TIPO con filtro de período."""
    return db.execute(f"""
        SELECT tv.nombre_tipo, COUNT(r.id_registro) as total_registros,
               COALESCE(SUM(r.valor_pagado),0) as recaudo_total,
               COALESCE(ROUND(AVG(r.valor_pagado),0),0) as recaudo_promedio,
               COALESCE(MAX(r.valor_pagado),0) as recaudo_maximo
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        WHERE r.estado='Cerrado' AND {filtro_sql}
        GROUP BY tv.id_tipo, tv.nombre_tipo
    """).fetchall()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 5: HELPERS Y DECORADORES
# ═══════════════════════════════════════════════════════════════════════════════

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def check_pw(p, h): return hash_pw(p) == h

def _log(db, accion, detalle=None):
    if 'user_id' in session:
        db.execute("INSERT INTO AUDITORIA(id_usuario,accion,detalle,ip) VALUES(?,?,?,?)",
                   (session['user_id'], accion, detalle, request.remote_addr))

def login_required(f):
    @wraps(f)
    def d(*a, **kw):
        if 'user_id' not in session: return redirect(url_for('login'))
        return f(*a, **kw)
    return d

def role_required(*roles):
    def dec(f):
        @wraps(f)
        def d(*a, **kw):
            if session.get('rol') not in roles:
                flash('Sin permisos para esta sección.', 'danger')
                return redirect(url_for('dashboard'))
            return f(*a, **kw)
        return d
    return dec

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 6: RUTAS DE LA APLICACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/', methods=['GET', 'POST'])
def login():
    if 'user_id' in session: return redirect(url_for('dashboard'))
    error = None
    if request.method == 'POST':
        correo = request.form['correo'].strip().lower()
        pw     = request.form['contrasena']
        db     = get_db()
        u = db.execute(
            "SELECT u.*,r.nombre_rol as rol_nombre FROM USUARIO u "
            "JOIN ROL r ON u.id_rol=r.id_rol WHERE u.correo=? AND u.activo=1",
            (correo,)
        ).fetchone()
        if u and check_pw(pw, u['contrasena_hash']):
            session.update({'user_id': u['id_usuario'], 'nombre': u['nombre'], 'rol': u['rol_nombre']})
            _log(db, 'LOGIN', f'Acceso: {correo}')
            db.commit(); db.close()
            return redirect(url_for('dashboard'))
        db.close()
        error = 'Correo o contraseña incorrectos.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        db = get_db(); _log(db, 'LOGOUT', 'Sesión cerrada'); db.commit(); db.close()
    session.clear()
    return redirect(url_for('login'))

@app.route('/registro', methods=['GET', 'POST'])
def registro():
    if request.method == 'POST':
        nombre   = request.form['nombre'].strip()
        apellido = request.form['apellido'].strip()
        correo   = request.form['correo'].strip().lower()
        pw1      = request.form['contrasena']
        pw2      = request.form['confirmar']
        if pw1 != pw2:               flash('Las contraseñas no coinciden.', 'danger')
        elif '@ecci.edu.co' not in correo: flash('Usa tu correo @ecci.edu.co.', 'danger')
        elif len(pw1) < 6:           flash('Mínimo 6 caracteres.', 'danger')
        else:
            db = get_db()
            try:
                db.execute("BEGIN")
                db.execute("INSERT INTO USUARIO(nombre,apellido,correo,contrasena_hash,id_rol) VALUES(?,?,?,?,3)",
                           (nombre, apellido, correo, hash_pw(pw1)))
                db.execute("COMMIT")
                flash('Cuenta creada. Inicia sesión.', 'success')
                db.close(); return redirect(url_for('login'))
            except sqlite3.IntegrityError:
                db.execute("ROLLBACK")
                flash('Correo ya registrado.', 'danger')
            finally: db.close()
    return render_template('registro.html')

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()

    # ── Datos generales (todos los roles) ─────────────────────────────────────
    total  = db.execute("SELECT COUNT(*) FROM ESPACIO").fetchone()[0]
    libres = db.execute("SELECT COUNT(*) FROM ESPACIO WHERE disponible=1").fetchone()[0]
    disp   = view_disponibilidad_tipo(db)
    chart_dona = json.dumps({
        'labels':   [r['nombre_tipo'] for r in disp],
        'ocupados': [r['espacios_ocupados'] for r in disp],
        'libres':   [r['espacios_libres']   for r in disp],
    })

    # ── Datos personales del usuario (todos los roles) ────────────────────────
    mis_vehiculos = db.execute("""
        SELECT v.placa, tv.nombre_tipo, v.marca, v.color
        FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        WHERE v.id_usuario=?
    """, (session['user_id'],)).fetchall()

    # Vehículo activo: si el usuario tiene un vehículo dentro ahora mismo
    vehiculo_activo = db.execute("""
        SELECT r.id_registro, r.placa, r.fecha_entrada, r.hora_entrada,
               e.codigo as espacio, tv.nombre_tipo,
               CAST((julianday('now') - julianday(r.fecha_entrada||' '||r.hora_entrada))*24*60 AS INTEGER) as minutos
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v  ON r.placa      = v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo = tv.id_tipo
        JOIN ESPACIO e   ON r.id_espacio = e.id_espacio
        WHERE v.id_usuario=? AND r.estado='Abierto'
        LIMIT 1
    """, (session['user_id'],)).fetchone()

    mis_registros = db.execute("""
        SELECT COUNT(*) FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        WHERE v.id_usuario=? AND r.estado='Cerrado'
    """, (session['user_id'],)).fetchone()[0]

    mi_gasto = db.execute("""
        SELECT COALESCE(SUM(r.valor_pagado),0) FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        WHERE v.id_usuario=? AND r.estado='Cerrado'
    """, (session['user_id'],)).fetchone()[0]

    # Últimos 3 registros propios
    mis_recientes = db.execute("""
        SELECT r.placa, r.fecha_entrada, r.hora_entrada,
               r.fecha_salida, r.hora_salida, r.valor_pagado, r.estado,
               e.codigo as espacio, tv.nombre_tipo
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        JOIN ESPACIO e ON r.id_espacio=e.id_espacio
        WHERE v.id_usuario=?
        ORDER BY r.id_registro DESC LIMIT 3
    """, (session['user_id'],)).fetchall()

    # ── Datos solo para Admin / Operario ──────────────────────────────────────
    activos = 0; rec_hoy = 0; t_hist = 0; recientes = []; r7 = []
    chart_linea = json.dumps({'labels': [], 'valores': []})
    if session['rol'] in ('Administrador', 'Operario'):
        activos = db.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE estado='Abierto'").fetchone()[0]
        rec_hoy = db.execute("SELECT COALESCE(SUM(valor_pagado),0) FROM REGISTRO_PARQUEO WHERE fecha_salida=date('now') AND estado='Cerrado'").fetchone()[0]
        t_hist  = db.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE estado='Cerrado'").fetchone()[0]
        recientes = db.execute("""
            SELECT r.id_registro, r.placa, r.fecha_entrada, r.hora_entrada, r.estado,
                   tv.nombre_tipo, e.codigo as espacio, u.nombre||' '||u.apellido as propietario
            FROM REGISTRO_PARQUEO r
            JOIN VEHICULO v ON r.placa=v.placa
            JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
            JOIN ESPACIO e ON r.id_espacio=e.id_espacio
            JOIN USUARIO u ON v.id_usuario=u.id_usuario
            ORDER BY r.id_registro DESC LIMIT 6
        """).fetchall()
        r7 = db.execute("""
            SELECT fecha_salida as fecha, COALESCE(SUM(valor_pagado),0) as total
            FROM REGISTRO_PARQUEO
            WHERE estado='Cerrado' AND fecha_salida>=date('now','-6 days')
            GROUP BY fecha_salida ORDER BY fecha_salida
        """).fetchall()
        chart_linea = json.dumps({'labels':[r['fecha'] for r in r7],'valores':[r['total'] for r in r7]})

    db.close()
    # Leer notificación de salida reciente (se muestra una sola vez)
    recien_salio = session.pop('recien_salio', None)
    return render_template('dashboard.html', recien_salio=recien_salio,
        total=total, libres=libres, ocupados=total-libres,
        activos=activos, recaudo_hoy=rec_hoy, total_hist=t_hist,
        recientes=recientes, chart_dona=chart_dona, chart_linea=chart_linea,
        mis_vehiculos=mis_vehiculos, vehiculo_activo=vehiculo_activo,
        mis_registros=mis_registros, mi_gasto=mi_gasto, mis_recientes=mis_recientes)

@app.route('/espacios')
@login_required
def espacios():
    db  = get_db()
    esp = view_ocupacion_actual(db)
    db.close()
    return render_template('espacios.html', espacios=esp)

@app.route('/api/espacios')
@login_required
def api_espacios():
    db  = get_db()
    esp = view_ocupacion_actual(db)
    db.close()
    return jsonify([dict(e) for e in esp])

@app.route('/api/stats')
@login_required
def api_stats():
    db = get_db()
    total  = db.execute("SELECT COUNT(*) FROM ESPACIO").fetchone()[0]
    libres = db.execute("SELECT COUNT(*) FROM ESPACIO WHERE disponible=1").fetchone()[0]
    rec    = db.execute("SELECT COALESCE(SUM(valor_pagado),0) FROM REGISTRO_PARQUEO WHERE fecha_salida=date('now') AND estado='Cerrado'").fetchone()[0]
    db.close()
    return jsonify({'total': total, 'libres': libres, 'ocupados': total-libres, 'recaudo_hoy': rec})

@app.route('/vehiculos', methods=['GET', 'POST'])
@login_required
def vehiculos():
    db = get_db()
    if request.method == 'POST':
        placa   = request.form['placa'].strip().upper()
        id_tipo = int(request.form['id_tipo'])
        marca   = request.form.get('marca','').strip() or None
        modelo  = request.form.get('modelo','').strip() or None
        color   = request.form.get('color','').strip() or None
        id_u    = int(request.form.get('id_usuario') or session['user_id'])
        try:
            db.execute("BEGIN")
            db.execute("INSERT INTO VEHICULO VALUES(?,?,?,?,?,?)", (placa,id_tipo,marca,modelo,color,id_u))
            _log(db,'VEHICULO_REGISTRADO',f'Placa:{placa}')
            db.execute("COMMIT")
            flash(f'Vehículo {placa} registrado.', 'success')
        except sqlite3.IntegrityError:
            db.execute("ROLLBACK")
            flash('Esa placa ya está registrada.', 'danger')
        db.close()
        return redirect(url_for('vehiculos'))

    q    = request.args.get('q','').strip()
    base = "SELECT v.*,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo JOIN USUARIO u ON v.id_usuario=u.id_usuario"
    if session['rol'] in ('Administrador','Operario'):
        veh = db.execute(base+(" WHERE v.placa LIKE ? OR u.nombre LIKE ? OR u.apellido LIKE ? ORDER BY v.placa" if q else " ORDER BY v.placa"),
                         ([f'%{q}%']*3 if q else [])).fetchall()
    else:
        veh = db.execute(base+" WHERE v.id_usuario=? ORDER BY v.placa", (session['user_id'],)).fetchall()

    tipos    = db.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo").fetchall()
    usuarios = db.execute("SELECT id_usuario,nombre||' '||apellido as nombre FROM USUARIO WHERE activo=1").fetchall()
    db.close()
    return render_template('vehiculos.html', vehiculos=veh, tipos=tipos, usuarios=usuarios, busqueda=q)

@app.route('/checkin', methods=['GET', 'POST'])
@login_required
@role_required('Administrador', 'Operario')
def checkin():
    if request.method == 'POST':
        placa = request.form['placa'].strip().upper()
        # Llama al procedimiento sp_checkin
        ok, msg, espacio = sp_checkin(placa, session['user_id'])
        flash(('✓ ' if ok else '') + msg, 'success' if ok else 'danger')
        return redirect(url_for('checkin'))

    db = get_db()
    placas      = db.execute("SELECT v.placa,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo ORDER BY v.placa").fetchall()
    libres_tipo = db.execute("SELECT tv.nombre_tipo,COUNT(*) as libres FROM ESPACIO e JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo WHERE e.disponible=1 GROUP BY tv.nombre_tipo").fetchall()
    db.close()
    return render_template('checkin.html', placas=placas, libres_tipo=libres_tipo)

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
@role_required('Administrador', 'Operario')
def checkout():
    ticket = None
    if request.method == 'POST':
        id_reg = int(request.form['id_registro'])
        # Llama al procedimiento sp_checkout
        ok, msg, ticket = sp_checkout(id_reg)
        flash(('✓ ' if ok else '') + msg, 'success' if ok else 'danger')

    db = get_db()
    abiertos = db.execute("""
        SELECT r.id_registro,r.placa,r.fecha_entrada,r.hora_entrada,
               e.codigo as espacio,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario,
               CAST((julianday('now')-julianday(r.fecha_entrada||' '||r.hora_entrada))*24 AS REAL) as horas
        FROM REGISTRO_PARQUEO r
        JOIN ESPACIO e ON r.id_espacio=e.id_espacio
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        JOIN USUARIO u ON v.id_usuario=u.id_usuario
        WHERE r.estado='Abierto' ORDER BY r.fecha_entrada,r.hora_entrada
    """).fetchall()
    db.close()
    return render_template('checkout.html', registros=abiertos, ticket=ticket)

@app.route('/reportes')
@login_required
@role_required('Administrador')
def reportes():
    periodo = request.args.get('periodo','semana')
    bp      = request.args.get('placa','').strip().upper()
    filtros = {'dia':"r.fecha_salida=date('now')",'semana':"r.fecha_salida>=date('now','-6 days')",'mes':"r.fecha_salida>=date('now','-29 days')"}
    filtro  = filtros.get(periodo, filtros['semana'])
    db      = get_db()
    recaudo = view_recaudo_tipo(db, filtro)
    q       = "WHERE r.estado='Cerrado'"
    params  = []
    if bp: q += " AND r.placa LIKE ?"; params.append(f'%{bp}%')
    historial = db.execute(f"SELECT r.*,e.codigo as espacio,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo JOIN ESPACIO e ON r.id_espacio=e.id_espacio JOIN USUARIO u ON v.id_usuario=u.id_usuario {q} ORDER BY r.id_registro DESC LIMIT 100", params).fetchall()
    db.close()
    return render_template('reportes.html', recaudo=recaudo, historial=historial, periodo=periodo, busqueda_placa=bp)

@app.route('/reportes/exportar')
@login_required
@role_required('Administrador')
def exportar_csv():
    periodo = request.args.get('periodo','semana')
    filtros = {'dia':"r.fecha_salida=date('now')",'semana':"r.fecha_salida>=date('now','-6 days')",'mes':"r.fecha_salida>=date('now','-29 days')"}
    filtro  = filtros.get(periodo, filtros['semana'])
    db      = get_db()
    rows    = db.execute(f"SELECT r.id_registro,r.placa,tv.nombre_tipo,e.codigo as espacio,u.nombre||' '||u.apellido as propietario,r.fecha_entrada,r.hora_entrada,r.fecha_salida,r.hora_salida,r.valor_pagado FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo JOIN ESPACIO e ON r.id_espacio=e.id_espacio JOIN USUARIO u ON v.id_usuario=u.id_usuario WHERE r.estado='Cerrado' AND {filtro} ORDER BY r.id_registro DESC").fetchall()
    _log(db,'EXPORTAR_CSV',f'Período:{periodo}'); db.commit(); db.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Placa','Tipo','Espacio','Propietario','Fecha Entrada','Hora Entrada','Fecha Salida','Hora Salida','Valor Pagado'])
    for r in rows: w.writerow([r['id_registro'],r['placa'],r['nombre_tipo'],r['espacio'],r['propietario'],r['fecha_entrada'],r['hora_entrada'],r['fecha_salida'],r['hora_salida'],r['valor_pagado']])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=neopark_{periodo}.csv'})

@app.route('/usuarios')
@login_required
@role_required('Administrador')
def usuarios():
    db = get_db()
    u  = db.execute("SELECT u.*,r.nombre_rol FROM USUARIO u JOIN ROL r ON u.id_rol=r.id_rol ORDER BY u.id_usuario").fetchall()
    roles = db.execute("SELECT * FROM ROL ORDER BY id_rol").fetchall()
    db.close()
    return render_template('usuarios.html', usuarios=u, roles=roles)

@app.route('/usuarios/toggle/<int:uid>')
@login_required
@role_required('Administrador')
def toggle_usuario(uid):
    if uid == session['user_id']:
        flash('No puedes desactivarte a ti mismo.', 'danger')
        return redirect(url_for('usuarios'))
    db = get_db()
    u  = db.execute("SELECT activo,correo FROM USUARIO WHERE id_usuario=?", (uid,)).fetchone()
    nuevo = 0 if u['activo'] else 1
    db.execute("UPDATE USUARIO SET activo=? WHERE id_usuario=?", (nuevo, uid))
    _log(db,'USUARIO_TOGGLE',f'{u["correo"]}→{"Activo" if nuevo else "Inactivo"}')
    db.commit(); db.close()
    flash(f'Usuario {"activado" if nuevo else "desactivado"}.', 'success')
    return redirect(url_for('usuarios'))

@app.route('/tarifas', methods=['GET', 'POST'])
@login_required
@role_required('Administrador')
def tarifas():
    if request.method == 'POST':
        id_tipo  = int(request.form['id_tipo'])
        valor    = float(request.form['valor_por_hora'])
        fraccion = int(request.form.get('fraccion_minutos', 15))
        # Llama al procedimiento sp_actualizar_tarifa
        ok, msg = sp_actualizar_tarifa(id_tipo, valor, fraccion)
        flash(msg, 'success' if ok else 'danger')

    db = get_db()
    t     = db.execute("SELECT t.*,tv.nombre_tipo FROM TARIFA t JOIN TIPO_VEHICULO tv ON t.id_tipo=tv.id_tipo ORDER BY t.activo DESC,t.fecha_vigencia DESC").fetchall()
    tipos = db.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo").fetchall()
    db.close()
    return render_template('tarifas.html', tarifas=t, tipos=tipos)

@app.route('/historial')
@login_required
def historial():
    bp   = request.args.get('placa','').strip().upper()
    db   = get_db()
    base = "SELECT r.*,e.codigo as espacio,tv.nombre_tipo FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo JOIN ESPACIO e ON r.id_espacio=e.id_espacio WHERE v.id_usuario=?"
    h    = db.execute(base+(" AND r.placa LIKE ? ORDER BY r.id_registro DESC" if bp else " ORDER BY r.id_registro DESC"),
                      ([session['user_id'], f'%{bp}%'] if bp else [session['user_id']])).fetchall()
    db.close()
    return render_template('historial.html', registros=h, busqueda=bp)

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    db = get_db()
    if request.method == 'POST':
        actual = request.form['contrasena_actual']
        nueva  = request.form['contrasena_nueva']
        conf   = request.form['confirmar']
        u      = db.execute("SELECT contrasena_hash FROM USUARIO WHERE id_usuario=?", (session['user_id'],)).fetchone()
        if not check_pw(actual, u['contrasena_hash']): flash('Contraseña actual incorrecta.', 'danger')
        elif nueva != conf:  flash('Las contraseñas nuevas no coinciden.', 'danger')
        elif len(nueva) < 6: flash('Mínimo 6 caracteres.', 'danger')
        else:
            db.execute("BEGIN")
            db.execute("UPDATE USUARIO SET contrasena_hash=? WHERE id_usuario=?", (hash_pw(nueva), session['user_id']))
            _log(db,'CAMBIO_CONTRASENA','Contraseña actualizada')
            db.execute("COMMIT")
            flash('Contraseña actualizada exitosamente.', 'success')
    usuario  = db.execute("SELECT u.*,r.nombre_rol FROM USUARIO u JOIN ROL r ON u.id_rol=r.id_rol WHERE u.id_usuario=?", (session['user_id'],)).fetchone()
    mis_veh  = db.execute("SELECT v.*,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.id_usuario=?", (session['user_id'],)).fetchall()
    db.close()
    return render_template('perfil.html', usuario=usuario, mis_vehiculos=mis_veh)

@app.route('/auditoria')
@login_required
@role_required('Administrador')
def auditoria():
    db   = get_db()
    logs = db.execute("SELECT a.*,u.nombre||' '||u.apellido as usuario_nombre,u.correo FROM AUDITORIA a JOIN USUARIO u ON a.id_usuario=u.id_usuario ORDER BY a.id_auditoria DESC LIMIT 200").fetchall()
    db.close()
    return render_template('auditoria.html', logs=logs)

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)

# ═══════════════════════════════════════════════════════════════════════════════
# CRUD: Editar y eliminar vehículos
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/vehiculos/editar/<placa>', methods=['GET','POST'])
@login_required
def editar_vehiculo(placa):
    db = get_db()
    veh = db.execute("SELECT v.*,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=?", (placa,)).fetchone()
    if not veh:
        flash('Vehículo no encontrado.','danger'); db.close(); return redirect(url_for('vehiculos'))
    # Solo admin/operario o el propio dueño
    if session['rol'] not in ('Administrador','Operario') and veh['id_usuario'] != session['user_id']:
        flash('Sin permisos.','danger'); db.close(); return redirect(url_for('vehiculos'))
    if request.method == 'POST':
        id_tipo = int(request.form['id_tipo'])
        marca   = request.form.get('marca','').strip() or None
        modelo  = request.form.get('modelo','').strip() or None
        color   = request.form.get('color','').strip() or None
        db.execute("BEGIN")
        db.execute("UPDATE VEHICULO SET id_tipo=?,marca=?,modelo=?,color=? WHERE placa=?",
                   (id_tipo,marca,modelo,color,placa))
        _log(db,'VEHICULO_EDITADO',f'Placa:{placa}')
        db.execute("COMMIT")
        flash(f'Vehículo {placa} actualizado.','success')
        db.close(); return redirect(url_for('vehiculos'))
    tipos = db.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo").fetchall()
    db.close()
    return render_template('editar_vehiculo.html', veh=veh, tipos=tipos)

@app.route('/vehiculos/eliminar/<placa>', methods=['POST'])
@login_required
def eliminar_vehiculo(placa):
    db = get_db()
    veh = db.execute("SELECT * FROM VEHICULO WHERE placa=?", (placa,)).fetchone()
    if not veh:
        flash('Vehículo no encontrado.','danger'); db.close(); return redirect(url_for('vehiculos'))
    if session['rol'] not in ('Administrador','Operario') and veh['id_usuario'] != session['user_id']:
        flash('Sin permisos.','danger'); db.close(); return redirect(url_for('vehiculos'))
    # Verificar que no tenga registro abierto
    activo = db.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE placa=? AND estado='Abierto'",(placa,)).fetchone()[0]
    if activo:
        flash('No se puede eliminar: el vehículo está dentro del parqueadero.','danger')
        db.close(); return redirect(url_for('vehiculos'))
    try:
        db.execute("BEGIN")
        db.execute("DELETE FROM VEHICULO WHERE placa=?", (placa,))
        _log(db,'VEHICULO_ELIMINADO',f'Placa:{placa}')
        db.execute("COMMIT")
        flash(f'Vehículo {placa} eliminado.','success')
    except Exception as e:
        db.execute("ROLLBACK")
        flash(f'No se puede eliminar: tiene historial de parqueos asociado.','danger')
    db.close(); return redirect(url_for('vehiculos'))

# ═══════════════════════════════════════════════════════════════════════════════
# CRUD: Editar rol de usuario (admin)
# ═══════════════════════════════════════════════════════════════════════════════

@app.route('/usuarios/editar/<int:uid>', methods=['POST'])
@login_required
@role_required('Administrador')
def editar_usuario(uid):
    if uid == session['user_id']:
        flash('No puedes editar tu propio rol.','danger'); return redirect(url_for('usuarios'))
    id_rol = int(request.form['id_rol'])
    db = get_db()
    db.execute("BEGIN")
    db.execute("UPDATE USUARIO SET id_rol=? WHERE id_usuario=?", (id_rol, uid))
    _log(db,'USUARIO_ROL_CAMBIADO',f'ID:{uid} → Rol:{id_rol}')
    db.execute("COMMIT")
    flash('Rol actualizado.','success')
    db.close(); return redirect(url_for('usuarios'))
