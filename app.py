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
import os, hashlib, math, csv, io, json, threading
import psycopg2
import psycopg2.extras

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'neopark-ecci-2026-pro')

# ── URL de PostgreSQL (variable de entorno que pone Render automáticamente) ───
DATABASE_URL = os.environ.get('DATABASE_URL')

# ── CONCURRENCIA: Lock global para operaciones críticas de check-in/out ───────
_db_lock = threading.Lock()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 1: CONEXIÓN Y INICIALIZACIÓN
# ═══════════════════════════════════════════════════════════════════════════════

def get_db():
    """Abre una nueva conexión a PostgreSQL con RealDictCursor (equivale a Row)."""
    conn = psycopg2.connect(DATABASE_URL)
    conn.autocommit = False
    return conn

def dict_row(cursor):
    """Convierte fetchall/fetchone a lista de dicts (igual que sqlite3.Row)."""
    cols = [d[0] for d in cursor.description]
    def make(row):
        return dict(zip(cols, row)) if row else None
    return make

def fetchall(cursor):
    cols = [d[0] for d in cursor.description]
    return [dict(zip(cols, row)) for row in cursor.fetchall()]

def fetchone(cursor):
    cols = [d[0] for d in cursor.description]
    row  = cursor.fetchone()
    return dict(zip(cols, row)) if row else None

def init_db():
    """Crea el esquema y datos iniciales si no existen."""
    conn = get_db()
    cur  = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS ROL (
            id_rol SERIAL PRIMARY KEY,
            nombre_rol TEXT NOT NULL UNIQUE,
            descripcion TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS TIPO_VEHICULO (
            id_tipo SERIAL PRIMARY KEY,
            nombre_tipo TEXT NOT NULL UNIQUE,
            descripcion TEXT);
        CREATE TABLE IF NOT EXISTS USUARIO (
            id_usuario SERIAL PRIMARY KEY,
            nombre TEXT NOT NULL, apellido TEXT NOT NULL,
            correo TEXT NOT NULL UNIQUE, contrasena_hash TEXT NOT NULL,
            id_rol INTEGER NOT NULL DEFAULT 3, activo INTEGER NOT NULL DEFAULT 1,
            fecha_registro TEXT NOT NULL DEFAULT (to_char(NOW(),'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (id_rol) REFERENCES ROL(id_rol) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS VEHICULO (
            placa TEXT PRIMARY KEY, id_tipo INTEGER NOT NULL,
            marca TEXT, modelo TEXT, color TEXT, id_usuario INTEGER NOT NULL,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT,
            FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS ESPACIO (
            id_espacio SERIAL PRIMARY KEY,
            codigo TEXT NOT NULL UNIQUE, id_tipo INTEGER NOT NULL,
            disponible INTEGER NOT NULL DEFAULT 1,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS TARIFA (
            id_tarifa SERIAL PRIMARY KEY, id_tipo INTEGER NOT NULL,
            valor_por_hora REAL NOT NULL, fraccion_minutos INTEGER NOT NULL DEFAULT 15,
            activo INTEGER NOT NULL DEFAULT 1, fecha_vigencia TEXT NOT NULL,
            FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT,
            CHECK (valor_por_hora > 0), CHECK (fraccion_minutos > 0));
        CREATE TABLE IF NOT EXISTS REGISTRO_PARQUEO (
            id_registro SERIAL PRIMARY KEY,
            placa TEXT NOT NULL, id_espacio INTEGER NOT NULL,
            fecha_entrada TEXT NOT NULL, hora_entrada TEXT NOT NULL,
            fecha_salida TEXT, hora_salida TEXT,
            valor_pagado REAL,
            estado TEXT NOT NULL DEFAULT 'Abierto'
                CHECK(estado IN ('Abierto','Cerrado')),
            FOREIGN KEY (placa) REFERENCES VEHICULO(placa) ON DELETE RESTRICT,
            FOREIGN KEY (id_espacio) REFERENCES ESPACIO(id_espacio) ON DELETE RESTRICT);
        CREATE TABLE IF NOT EXISTS AUDITORIA (
            id_auditoria SERIAL PRIMARY KEY,
            id_usuario INTEGER NOT NULL, accion TEXT NOT NULL,
            detalle TEXT, ip TEXT,
            fecha_hora TEXT NOT NULL DEFAULT (to_char(NOW(),'YYYY-MM-DD HH24:MI:SS')),
            FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario) ON DELETE RESTRICT);
    """)
    conn.commit()

    cur.execute("SELECT 1 FROM ROL LIMIT 1")
    if not cur.fetchone():
        _seed_data(conn, cur)

    conn.commit()
    cur.close()
    conn.close()

def _seed_data(conn, cur):
    def pw(p): return hashlib.sha256(p.encode()).hexdigest()

    cur.execute("""
        INSERT INTO ROL(nombre_rol,descripcion) VALUES
            ('Administrador','Acceso total al sistema'),
            ('Operario','Registro de entradas y salidas'),
            ('Usuario','Consulta e historial personal'),
            ('Auditor','Solo lectura'),
            ('Supervisor','Supervisión y reportes');
        INSERT INTO TIPO_VEHICULO(nombre_tipo,descripcion) VALUES
            ('Carro','Automóvil de cuatro ruedas'),
            ('Moto','Motocicleta de dos ruedas'),
            ('Bicicleta','Vehículo no motorizado'),
            ('Camioneta','Vehículo de carga liviana'),
            ('Patineta','Movilidad personal no motorizada');
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

    a = pw("Admin123!"); b = pw("Op123!"); c = pw("User123!")
    for row in [
        ('Justin','Infante','justisfe.infantecristancho@ecci.edu.co', a, 1),
        ('Jhon','Guzmán','jhone.guzmansalinas@ecci.edu.co', b, 2),
        ('Alejandro','Jiménez','alejoe.jimenezperez@ecci.edu.co', c, 3),
        ('Carlos','Rodríguez','c.rodriguez@ecci.edu.co', c, 3),
        ('María','López','m.lopez@ecci.edu.co', c, 3),
    ]:
        cur.execute(
            "INSERT INTO USUARIO(nombre,apellido,correo,contrasena_hash,id_rol) VALUES(%s,%s,%s,%s,%s)", row
        )

    cur.execute("""
        INSERT INTO VEHICULO(placa,id_tipo,marca,modelo,color,id_usuario) VALUES
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
            ('ABC123',1,to_char(NOW(),'YYYY-MM-DD'),to_char(NOW(),'HH24:MI:SS'),'Abierto'),
            ('XYZ789',4,to_char(NOW(),'YYYY-MM-DD'),to_char(NOW(),'HH24:MI:SS'),'Abierto');
        UPDATE ESPACIO SET disponible=0 WHERE id_espacio IN (1,4);
    """)
    conn.commit()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 2: FUNCIONES EQUIVALENTES A PL/SQL
# ═══════════════════════════════════════════════════════════════════════════════

def fn_calcular_cobro(cur, id_tipo, dt_entrada, dt_salida):
    cur.execute(
        "SELECT valor_por_hora, fraccion_minutos FROM TARIFA "
        "WHERE id_tipo=%s AND activo=1 ORDER BY fecha_vigencia DESC LIMIT 1",
        (id_tipo,)
    )
    tarifa = fetchone(cur)
    if not tarifa: return 0
    minutos    = max(0, (dt_salida - dt_entrada).total_seconds() / 60)
    fracciones = math.ceil(minutos / tarifa['fraccion_minutos']) if minutos > 0 else 0
    return round(fracciones * (tarifa['valor_por_hora'] / (60 / tarifa['fraccion_minutos'])), 0)

def fn_estado_parqueadero(cur, id_tipo):
    cur.execute("SELECT COUNT(*) FROM ESPACIO WHERE id_tipo=%s AND disponible=1", (id_tipo,))
    libres = cur.fetchone()[0]
    if libres == 0: return 'OCUPACION_TOTAL'
    if libres <= 2: return 'CASI_LLENO'
    return 'DISPONIBLE'

def fn_usuario_tiene_activo(cur, id_usuario):
    cur.execute(
        "SELECT COUNT(*) FROM REGISTRO_PARQUEO r "
        "JOIN VEHICULO v ON r.placa=v.placa "
        "WHERE v.id_usuario=%s AND r.estado='Abierto'", (id_usuario,)
    )
    return cur.fetchone()[0] > 0

def duracion_str(dt_e, dt_s=None):
    if dt_s is None: dt_s = datetime.now()
    delta = dt_s - dt_e
    h = int(delta.total_seconds() // 3600)
    m = int((delta.total_seconds() % 3600) // 60)
    return f"{h}h {m}min"

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 3: PROCEDIMIENTOS EQUIVALENTES A PL/SQL
# ═══════════════════════════════════════════════════════════════════════════════

def sp_checkin(placa, id_usuario):
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT v.*, tv.nombre_tipo FROM VEHICULO v "
                "JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=%s",
                (placa,)
            )
            veh = fetchone(cur)
            if not veh:
                return False, 'ERROR RN1: Vehículo no registrado en el sistema', None

            if fn_usuario_tiene_activo(cur, veh['id_usuario']):
                return False, 'ERROR RN2: El propietario ya tiene un vehículo dentro', None

            cur.execute(
                "SELECT * FROM ESPACIO WHERE id_tipo=%s AND disponible=1 LIMIT 1",
                (veh['id_tipo'],)
            )
            espacio = fetchone(cur)
            if not espacio:
                estado = fn_estado_parqueadero(cur, veh['id_tipo'])
                return False, f'ERROR RN4: {estado} — Sin espacios para {veh["nombre_tipo"]}', None

            now = datetime.now()
            cur.execute(
                "INSERT INTO REGISTRO_PARQUEO(placa,id_espacio,fecha_entrada,hora_entrada,estado) "
                "VALUES(%s,%s,%s,%s,'Abierto')",
                (placa, espacio['id_espacio'], now.strftime('%Y-%m-%d'), now.strftime('%H:%M:%S'))
            )
            cur.execute("UPDATE ESPACIO SET disponible=0 WHERE id_espacio=%s", (espacio['id_espacio'],))
            _log(cur, 'CHECKIN', f'Placa:{placa} → Espacio:{espacio["codigo"]}')
            conn.commit()
            return True, f'Check-in exitoso — Espacio asignado: {espacio["codigo"]}', espacio['codigo']

        except Exception as e:
            conn.rollback()
            return False, f'ERROR inesperado: {str(e)}', None
        finally:
            conn.close()

def sp_checkout(id_registro):
    with _db_lock:
        conn = get_db()
        try:
            cur = conn.cursor()

            cur.execute(
                "SELECT * FROM REGISTRO_PARQUEO WHERE id_registro=%s AND estado='Abierto'",
                (id_registro,)
            )
            reg = fetchone(cur)
            if not reg:
                return False, 'Registro no encontrado o ya cerrado', None

            cur.execute(
                "SELECT v.*,tv.nombre_tipo FROM VEHICULO v "
                "JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=%s",
                (reg['placa'],)
            )
            veh = fetchone(cur)

            cur.execute(
                "SELECT nombre||' '||apellido as nombre FROM USUARIO WHERE id_usuario=%s",
                (veh['id_usuario'],)
            )
            prop = fetchone(cur)

            cur.execute("SELECT codigo FROM ESPACIO WHERE id_espacio=%s", (reg['id_espacio'],))
            esp = fetchone(cur)

            dt_e = datetime.strptime(f"{reg['fecha_entrada']} {reg['hora_entrada']}", '%Y-%m-%d %H:%M:%S')
            dt_s = datetime.now()

            if dt_s <= dt_e:
                return False, 'La hora de salida debe ser posterior a la entrada', None

            valor = fn_calcular_cobro(cur, veh['id_tipo'], dt_e, dt_s)
            dur   = duracion_str(dt_e, dt_s)

            cur.execute(
                "UPDATE REGISTRO_PARQUEO SET fecha_salida=%s,hora_salida=%s,valor_pagado=%s,estado='Cerrado' "
                "WHERE id_registro=%s",
                (dt_s.strftime('%Y-%m-%d'), dt_s.strftime('%H:%M:%S'), valor, id_registro)
            )
            cur.execute("UPDATE ESPACIO SET disponible=1 WHERE id_espacio=%s", (reg['id_espacio'],))

            ticket = {
                'id_registro': id_registro, 'placa': reg['placa'],
                'tipo': veh['nombre_tipo'], 'espacio': esp['codigo'],
                'propietario': prop['nombre'],
                'entrada': f"{reg['fecha_entrada']} {reg['hora_entrada'][:5]}",
                'salida': dt_s.strftime('%Y-%m-%d %H:%M'),
                'duracion': dur, 'valor': int(valor),
            }
            _log(cur, 'CHECKOUT', f'Placa:{reg["placa"]},Valor:${int(valor):,},Dur:{dur}')
            conn.commit()

            if 'user_id' in session:
                session['recien_salio'] = {
                    'placa': reg['placa'], 'espacio': esp['codigo'],
                    'duracion': dur, 'valor': int(valor)
                }
            return True, f'Check-out completado. Valor: ${int(valor):,}', ticket

        except Exception as e:
            conn.rollback()
            return False, f'ERROR: {str(e)}', None
        finally:
            conn.close()

def sp_actualizar_tarifa(id_tipo, valor_hora, fraccion):
    if valor_hora <= 0:
        return False, 'El valor por hora debe ser mayor a 0'
    conn = get_db()
    try:
        cur = conn.cursor()
        cur.execute("UPDATE TARIFA SET activo=0 WHERE id_tipo=%s", (id_tipo,))
        cur.execute(
            "INSERT INTO TARIFA(id_tipo,valor_por_hora,fraccion_minutos,activo,fecha_vigencia) "
            "VALUES(%s,%s,%s,1,to_char(NOW(),'YYYY-MM-DD'))", (id_tipo, valor_hora, fraccion)
        )
        _log(cur, 'TARIFA_ACTUALIZADA', f'Tipo:{id_tipo},Valor:${valor_hora:,.0f}')
        conn.commit()
        return True, f'Tarifa actualizada a ${valor_hora:,.0f}/hora'
    except Exception as e:
        conn.rollback()
        return False, f'ERROR: {str(e)}'
    finally:
        conn.close()

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 4: VISTAS EQUIVALENTES
# ═══════════════════════════════════════════════════════════════════════════════

def view_ocupacion_actual(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT e.id_espacio, e.codigo, tv.nombre_tipo,
               CASE WHEN e.disponible=1 THEN 'Libre' ELSE 'Ocupado' END as estado,
               e.disponible,
               r.placa, r.fecha_entrada, r.hora_entrada,
               u.nombre||' '||u.apellido as propietario,
               CAST(EXTRACT(EPOCH FROM (NOW() - (r.fecha_entrada||' '||r.hora_entrada)::timestamp))/60 AS INTEGER) as minutos_transcurridos,
               CASE WHEN e.disponible=1 THEN 'Libre' ELSE 'Ocupado' END as estado_texto
        FROM ESPACIO e
        JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo
        LEFT JOIN REGISTRO_PARQUEO r ON r.id_espacio=e.id_espacio AND r.estado='Abierto'
        LEFT JOIN VEHICULO v ON r.placa=v.placa
        LEFT JOIN USUARIO u ON v.id_usuario=u.id_usuario
        ORDER BY e.codigo
    """)
    return fetchall(cur)

def view_disponibilidad_tipo(conn):
    cur = conn.cursor()
    cur.execute("""
        SELECT tv.nombre_tipo,
               COUNT(e.id_espacio) as total_espacios,
               SUM(e.disponible) as espacios_libres,
               SUM(1-e.disponible) as espacios_ocupados,
               ROUND(CAST(SUM(1-e.disponible) AS NUMERIC)/COUNT(e.id_espacio)*100,1) as porcentaje_ocupacion
        FROM ESPACIO e JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo
        GROUP BY tv.id_tipo, tv.nombre_tipo
    """)
    return fetchall(cur)

def view_recaudo_tipo(conn, filtro_sql):
    cur = conn.cursor()
    cur.execute(f"""
        SELECT tv.nombre_tipo, COUNT(r.id_registro) as total_registros,
               COALESCE(SUM(r.valor_pagado),0) as recaudo_total,
               COALESCE(ROUND(AVG(r.valor_pagado)::numeric,0),0) as recaudo_promedio,
               COALESCE(MAX(r.valor_pagado),0) as recaudo_maximo
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        WHERE r.estado='Cerrado' AND {filtro_sql}
        GROUP BY tv.id_tipo, tv.nombre_tipo
    """)
    return fetchall(cur)

# ═══════════════════════════════════════════════════════════════════════════════
# SECCIÓN 5: HELPERS Y DECORADORES
# ═══════════════════════════════════════════════════════════════════════════════

def hash_pw(p): return hashlib.sha256(p.encode()).hexdigest()
def check_pw(p, h): return hash_pw(p) == h

def _log(cur, accion, detalle=None):
    if 'user_id' in session:
        cur.execute(
            "INSERT INTO AUDITORIA(id_usuario,accion,detalle,ip,fecha_hora) VALUES(%s,%s,%s,%s,to_char(NOW(),'YYYY-MM-DD HH24:MI:SS'))",
            (session['user_id'], accion, detalle, request.remote_addr)
        )

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
        conn   = get_db()
        cur    = conn.cursor()
        cur.execute(
            "SELECT u.*,r.nombre_rol as rol_nombre FROM USUARIO u "
            "JOIN ROL r ON u.id_rol=r.id_rol WHERE u.correo=%s AND u.activo=1",
            (correo,)
        )
        u = fetchone(cur)
        if u and check_pw(pw, u['contrasena_hash']):
            session.update({'user_id': u['id_usuario'], 'nombre': u['nombre'], 'rol': u['rol_nombre']})
            _log(cur, 'LOGIN', f'Acceso: {correo}')
            conn.commit(); conn.close()
            return redirect(url_for('dashboard'))
        conn.close()
        error = 'Correo o contraseña incorrectos.'
    return render_template('login.html', error=error)

@app.route('/logout')
def logout():
    if 'user_id' in session:
        conn = get_db(); cur = conn.cursor()
        _log(cur, 'LOGOUT', 'Sesión cerrada')
        conn.commit(); conn.close()
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
        if pw1 != pw2:
            flash('Las contraseñas no coinciden.', 'danger')
        elif '@ecci.edu.co' not in correo:
            flash('Usa tu correo @ecci.edu.co.', 'danger')
        elif len(pw1) < 6:
            flash('Mínimo 6 caracteres.', 'danger')
        else:
            conn = get_db(); cur = conn.cursor()
            try:
                cur.execute(
                    "INSERT INTO USUARIO(nombre,apellido,correo,contrasena_hash,id_rol) VALUES(%s,%s,%s,%s,3)",
                    (nombre, apellido, correo, hash_pw(pw1))
                )
                conn.commit()
                flash('Cuenta creada. Inicia sesión.', 'success')
                conn.close(); return redirect(url_for('login'))
            except psycopg2.IntegrityError:
                conn.rollback()
                flash('Correo ya registrado.', 'danger')
            finally:
                conn.close()
    return render_template('registro.html')

@app.route('/dashboard')
@login_required
def dashboard():
    conn = get_db()
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM ESPACIO"); total  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ESPACIO WHERE disponible=1"); libres = cur.fetchone()[0]
    disp = view_disponibilidad_tipo(conn)
    chart_dona = json.dumps({
        'labels':   [r['nombre_tipo'] for r in disp],
        'ocupados': [r['espacios_ocupados'] for r in disp],
        'libres':   [r['espacios_libres']   for r in disp],
    })

    cur.execute("""
        SELECT v.placa, tv.nombre_tipo, v.marca, v.color
        FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        WHERE v.id_usuario=%s
    """, (session['user_id'],))
    mis_vehiculos = fetchall(cur)

    cur.execute("""
        SELECT r.id_registro, r.placa, r.fecha_entrada, r.hora_entrada,
               e.codigo as espacio, tv.nombre_tipo,
               CAST(EXTRACT(EPOCH FROM (NOW() - (r.fecha_entrada||' '||r.hora_entrada)::timestamp))/60 AS INTEGER) as minutos
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v  ON r.placa      = v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo = tv.id_tipo
        JOIN ESPACIO e   ON r.id_espacio = e.id_espacio
        WHERE v.id_usuario=%s AND r.estado='Abierto'
        LIMIT 1
    """, (session['user_id'],))
    vehiculo_activo = fetchone(cur)

    cur.execute("""
        SELECT COUNT(*) FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        WHERE v.id_usuario=%s AND r.estado='Cerrado'
    """, (session['user_id'],))
    mis_registros = cur.fetchone()[0]

    cur.execute("""
        SELECT COALESCE(SUM(r.valor_pagado),0) FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        WHERE v.id_usuario=%s AND r.estado='Cerrado'
    """, (session['user_id'],))
    mi_gasto = cur.fetchone()[0]

    cur.execute("""
        SELECT r.placa, r.fecha_entrada, r.hora_entrada,
               r.fecha_salida, r.hora_salida, r.valor_pagado, r.estado,
               e.codigo as espacio, tv.nombre_tipo
        FROM REGISTRO_PARQUEO r
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        JOIN ESPACIO e ON r.id_espacio=e.id_espacio
        WHERE v.id_usuario=%s
        ORDER BY r.id_registro DESC LIMIT 3
    """, (session['user_id'],))
    mis_recientes = fetchall(cur)

    activos = 0; rec_hoy = 0; t_hist = 0; recientes = []; r7 = []
    chart_linea = json.dumps({'labels': [], 'valores': []})
    if session['rol'] in ('Administrador', 'Operario'):
        cur.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE estado='Abierto'")
        activos = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(valor_pagado),0) FROM REGISTRO_PARQUEO WHERE fecha_salida=to_char(NOW(),'YYYY-MM-DD') AND estado='Cerrado'")
        rec_hoy = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE estado='Cerrado'")
        t_hist = cur.fetchone()[0]
        cur.execute("""
            SELECT r.id_registro,r.placa,r.fecha_entrada,r.hora_entrada,r.estado,
                   tv.nombre_tipo, e.codigo as espacio, u.nombre||' '||u.apellido as propietario
            FROM REGISTRO_PARQUEO r
            JOIN VEHICULO v ON r.placa=v.placa
            JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
            JOIN ESPACIO e ON r.id_espacio=e.id_espacio
            JOIN USUARIO u ON v.id_usuario=u.id_usuario
            ORDER BY r.id_registro DESC LIMIT 6
        """)
        recientes = fetchall(cur)
        cur.execute("""
            SELECT fecha_salida as fecha, COALESCE(SUM(valor_pagado),0) as total
            FROM REGISTRO_PARQUEO
            WHERE estado='Cerrado' AND fecha_salida>=(NOW()-INTERVAL '6 days')::date::text
            GROUP BY fecha_salida ORDER BY fecha_salida
        """)
        r7 = fetchall(cur)
        chart_linea = json.dumps({'labels':[r['fecha'] for r in r7],'valores':[r['total'] for r in r7]})

    conn.close()
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
    conn = get_db()
    esp  = view_ocupacion_actual(conn)
    conn.close()
    return render_template('espacios.html', espacios=esp)

@app.route('/api/espacios')
@login_required
def api_espacios():
    conn = get_db()
    esp  = view_ocupacion_actual(conn)
    conn.close()
    return jsonify(esp)

@app.route('/api/stats')
@login_required
def api_stats():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM ESPACIO"); total  = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM ESPACIO WHERE disponible=1"); libres = cur.fetchone()[0]
    cur.execute("SELECT COALESCE(SUM(valor_pagado),0) FROM REGISTRO_PARQUEO WHERE fecha_salida=to_char(NOW(),'YYYY-MM-DD') AND estado='Cerrado'")
    rec = cur.fetchone()[0]
    conn.close()
    return jsonify({'total': total, 'libres': libres, 'ocupados': total-libres, 'recaudo_hoy': rec})

@app.route('/vehiculos', methods=['GET', 'POST'])
@login_required
def vehiculos():
    conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        placa   = request.form['placa'].strip().upper()
        id_tipo = int(request.form['id_tipo'])
        marca   = request.form.get('marca','').strip() or None
        modelo  = request.form.get('modelo','').strip() or None
        color   = request.form.get('color','').strip() or None
        id_u    = int(request.form.get('id_usuario') or session['user_id'])
        try:
            cur.execute("INSERT INTO VEHICULO(placa,id_tipo,marca,modelo,color,id_usuario) VALUES(%s,%s,%s,%s,%s,%s)",
                        (placa, id_tipo, marca, modelo, color, id_u))
            _log(cur, 'VEHICULO_REGISTRADO', f'Placa:{placa}')
            conn.commit()
            flash(f'Vehículo {placa} registrado.', 'success')
        except psycopg2.IntegrityError:
            conn.rollback()
            flash('Esa placa ya está registrada.', 'danger')
        conn.close()
        return redirect(url_for('vehiculos'))

    q = request.args.get('q','').strip()
    base = ("SELECT v.*,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario "
            "FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo "
            "JOIN USUARIO u ON v.id_usuario=u.id_usuario")
    if session['rol'] in ('Administrador','Operario'):
        if q:
            cur.execute(base+" WHERE v.placa ILIKE %s OR u.nombre ILIKE %s OR u.apellido ILIKE %s ORDER BY v.placa",
                        [f'%{q}%']*3)
        else:
            cur.execute(base+" ORDER BY v.placa")
    else:
        cur.execute(base+" WHERE v.id_usuario=%s ORDER BY v.placa", (session['user_id'],))
    veh = fetchall(cur)

    cur.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo")
    tipos = fetchall(cur)
    cur.execute("SELECT id_usuario,nombre||' '||apellido as nombre FROM USUARIO WHERE activo=1")
    usuarios = fetchall(cur)
    conn.close()
    return render_template('vehiculos.html', vehiculos=veh, tipos=tipos, usuarios=usuarios, busqueda=q)

@app.route('/checkin', methods=['GET', 'POST'])
@login_required
@role_required('Administrador', 'Operario')
def checkin():
    if request.method == 'POST':
        placa = request.form['placa'].strip().upper()
        ok, msg, espacio = sp_checkin(placa, session['user_id'])
        flash(('✓ ' if ok else '') + msg, 'success' if ok else 'danger')
        return redirect(url_for('checkin'))

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT v.placa,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo ORDER BY v.placa")
    placas = fetchall(cur)
    cur.execute("SELECT tv.nombre_tipo,COUNT(*) as libres FROM ESPACIO e JOIN TIPO_VEHICULO tv ON e.id_tipo=tv.id_tipo WHERE e.disponible=1 GROUP BY tv.nombre_tipo")
    libres_tipo = fetchall(cur)
    conn.close()
    return render_template('checkin.html', placas=placas, libres_tipo=libres_tipo)

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
@role_required('Administrador', 'Operario')
def checkout():
    ticket = None
    if request.method == 'POST':
        id_reg = int(request.form['id_registro'])
        ok, msg, ticket = sp_checkout(id_reg)
        flash(('✓ ' if ok else '') + msg, 'success' if ok else 'danger')

    conn = get_db(); cur = conn.cursor()
    cur.execute("""
        SELECT r.id_registro,r.placa,r.fecha_entrada,r.hora_entrada,
               e.codigo as espacio,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario,
               EXTRACT(EPOCH FROM (NOW()-(r.fecha_entrada||' '||r.hora_entrada)::timestamp))/3600 as horas
        FROM REGISTRO_PARQUEO r
        JOIN ESPACIO e ON r.id_espacio=e.id_espacio
        JOIN VEHICULO v ON r.placa=v.placa
        JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo
        JOIN USUARIO u ON v.id_usuario=u.id_usuario
        WHERE r.estado='Abierto' ORDER BY r.fecha_entrada,r.hora_entrada
    """)
    abiertos = fetchall(cur)
    conn.close()
    return render_template('checkout.html', registros=abiertos, ticket=ticket)

@app.route('/reportes')
@login_required
@role_required('Administrador')
def reportes():
    periodo = request.args.get('periodo','semana')
    bp      = request.args.get('placa','').strip().upper()
    filtros = {
        'dia':    "r.fecha_salida=to_char(NOW(),'YYYY-MM-DD')",
        'semana': "r.fecha_salida>=(NOW()-INTERVAL '6 days')::date::text",
        'mes':    "r.fecha_salida>=(NOW()-INTERVAL '29 days')::date::text",
    }
    filtro = filtros.get(periodo, filtros['semana'])
    conn   = get_db(); cur = conn.cursor()
    recaudo = view_recaudo_tipo(conn, filtro)
    q      = "WHERE r.estado='Cerrado'"
    params = []
    if bp: q += " AND r.placa ILIKE %s"; params.append(f'%{bp}%')
    cur.execute(
        f"SELECT r.*,e.codigo as espacio,tv.nombre_tipo,u.nombre||' '||u.apellido as propietario "
        f"FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa "
        f"JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo "
        f"JOIN ESPACIO e ON r.id_espacio=e.id_espacio "
        f"JOIN USUARIO u ON v.id_usuario=u.id_usuario {q} ORDER BY r.id_registro DESC LIMIT 100",
        params
    )
    historial = fetchall(cur)
    conn.close()
    return render_template('reportes.html', recaudo=recaudo, historial=historial, periodo=periodo, busqueda_placa=bp)

@app.route('/reportes/exportar')
@login_required
@role_required('Administrador')
def exportar_csv():
    periodo = request.args.get('periodo','semana')
    filtros = {
        'dia':    "r.fecha_salida=to_char(NOW(),'YYYY-MM-DD')",
        'semana': "r.fecha_salida>=(NOW()-INTERVAL '6 days')::date::text",
        'mes':    "r.fecha_salida>=(NOW()-INTERVAL '29 days')::date::text",
    }
    filtro = filtros.get(periodo, filtros['semana'])
    conn   = get_db(); cur = conn.cursor()
    cur.execute(
        f"SELECT r.id_registro,r.placa,tv.nombre_tipo,e.codigo as espacio,"
        f"u.nombre||' '||u.apellido as propietario,"
        f"r.fecha_entrada,r.hora_entrada,r.fecha_salida,r.hora_salida,r.valor_pagado "
        f"FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa "
        f"JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo "
        f"JOIN ESPACIO e ON r.id_espacio=e.id_espacio "
        f"JOIN USUARIO u ON v.id_usuario=u.id_usuario "
        f"WHERE r.estado='Cerrado' AND {filtro} ORDER BY r.id_registro DESC"
    )
    rows = fetchall(cur)
    _log(cur, 'EXPORTAR_CSV', f'Período:{periodo}')
    conn.commit(); conn.close()
    out = io.StringIO()
    w   = csv.writer(out)
    w.writerow(['ID','Placa','Tipo','Espacio','Propietario','Fecha Entrada','Hora Entrada','Fecha Salida','Hora Salida','Valor Pagado'])
    for r in rows:
        w.writerow([r['id_registro'],r['placa'],r['nombre_tipo'],r['espacio'],r['propietario'],
                    r['fecha_entrada'],r['hora_entrada'],r['fecha_salida'],r['hora_salida'],r['valor_pagado']])
    out.seek(0)
    return Response(out.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': f'attachment; filename=neopark_{periodo}.csv'})

@app.route('/usuarios')
@login_required
@role_required('Administrador')
def usuarios():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT u.*,r.nombre_rol FROM USUARIO u JOIN ROL r ON u.id_rol=r.id_rol ORDER BY u.id_usuario")
    u = fetchall(cur)
    cur.execute("SELECT * FROM ROL ORDER BY id_rol")
    roles = fetchall(cur)
    conn.close()
    return render_template('usuarios.html', usuarios=u, roles=roles)

@app.route('/usuarios/toggle/<int:uid>')
@login_required
@role_required('Administrador')
def toggle_usuario(uid):
    if uid == session['user_id']:
        flash('No puedes desactivarte a ti mismo.', 'danger')
        return redirect(url_for('usuarios'))
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT activo,correo FROM USUARIO WHERE id_usuario=%s", (uid,))
    u = fetchone(cur)
    nuevo = 0 if u['activo'] else 1
    cur.execute("UPDATE USUARIO SET activo=%s WHERE id_usuario=%s", (nuevo, uid))
    _log(cur, 'USUARIO_TOGGLE', f'{u["correo"]}→{"Activo" if nuevo else "Inactivo"}')
    conn.commit(); conn.close()
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
        ok, msg  = sp_actualizar_tarifa(id_tipo, valor, fraccion)
        flash(msg, 'success' if ok else 'danger')

    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT t.*,tv.nombre_tipo FROM TARIFA t JOIN TIPO_VEHICULO tv ON t.id_tipo=tv.id_tipo ORDER BY t.activo DESC,t.fecha_vigencia DESC")
    t = fetchall(cur)
    cur.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo")
    tipos = fetchall(cur)
    conn.close()
    return render_template('tarifas.html', tarifas=t, tipos=tipos)

@app.route('/historial')
@login_required
def historial():
    bp   = request.args.get('placa','').strip().upper()
    conn = get_db(); cur = conn.cursor()
    base = ("SELECT r.*,e.codigo as espacio,tv.nombre_tipo "
            "FROM REGISTRO_PARQUEO r JOIN VEHICULO v ON r.placa=v.placa "
            "JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo "
            "JOIN ESPACIO e ON r.id_espacio=e.id_espacio WHERE v.id_usuario=%s")
    if bp:
        cur.execute(base+" AND r.placa ILIKE %s ORDER BY r.id_registro DESC",
                    (session['user_id'], f'%{bp}%'))
    else:
        cur.execute(base+" ORDER BY r.id_registro DESC", (session['user_id'],))
    h = fetchall(cur)
    conn.close()
    return render_template('historial.html', registros=h, busqueda=bp)

@app.route('/perfil', methods=['GET', 'POST'])
@login_required
def perfil():
    conn = get_db(); cur = conn.cursor()
    if request.method == 'POST':
        actual = request.form['contrasena_actual']
        nueva  = request.form['contrasena_nueva']
        conf   = request.form['confirmar']
        cur.execute("SELECT contrasena_hash FROM USUARIO WHERE id_usuario=%s", (session['user_id'],))
        u = fetchone(cur)
        if not check_pw(actual, u['contrasena_hash']):
            flash('Contraseña actual incorrecta.', 'danger')
        elif nueva != conf:
            flash('Las contraseñas nuevas no coinciden.', 'danger')
        elif len(nueva) < 6:
            flash('Mínimo 6 caracteres.', 'danger')
        else:
            cur.execute("UPDATE USUARIO SET contrasena_hash=%s WHERE id_usuario=%s",
                        (hash_pw(nueva), session['user_id']))
            _log(cur, 'CAMBIO_CONTRASENA', 'Contraseña actualizada')
            conn.commit()
            flash('Contraseña actualizada exitosamente.', 'success')
    cur.execute("SELECT u.*,r.nombre_rol FROM USUARIO u JOIN ROL r ON u.id_rol=r.id_rol WHERE u.id_usuario=%s",
                (session['user_id'],))
    usuario = fetchone(cur)
    cur.execute("SELECT v.*,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.id_usuario=%s",
                (session['user_id'],))
    mis_veh = fetchall(cur)
    conn.close()
    return render_template('perfil.html', usuario=usuario, mis_vehiculos=mis_veh)

@app.route('/auditoria')
@login_required
@role_required('Administrador')
def auditoria():
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT a.*,u.nombre||' '||u.apellido as usuario_nombre,u.correo FROM AUDITORIA a JOIN USUARIO u ON a.id_usuario=u.id_usuario ORDER BY a.id_auditoria DESC LIMIT 200")
    logs = fetchall(cur)
    conn.close()
    return render_template('auditoria.html', logs=logs)

@app.route('/vehiculos/editar/<placa>', methods=['GET','POST'])
@login_required
def editar_vehiculo(placa):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT v.*,tv.nombre_tipo FROM VEHICULO v JOIN TIPO_VEHICULO tv ON v.id_tipo=tv.id_tipo WHERE v.placa=%s", (placa,))
    veh = fetchone(cur)
    if not veh:
        flash('Vehículo no encontrado.','danger'); conn.close(); return redirect(url_for('vehiculos'))
    if session['rol'] not in ('Administrador','Operario') and veh['id_usuario'] != session['user_id']:
        flash('Sin permisos.','danger'); conn.close(); return redirect(url_for('vehiculos'))
    if request.method == 'POST':
        id_tipo = int(request.form['id_tipo'])
        marca   = request.form.get('marca','').strip() or None
        modelo  = request.form.get('modelo','').strip() or None
        color   = request.form.get('color','').strip() or None
        cur.execute("UPDATE VEHICULO SET id_tipo=%s,marca=%s,modelo=%s,color=%s WHERE placa=%s",
                    (id_tipo, marca, modelo, color, placa))
        _log(cur, 'VEHICULO_EDITADO', f'Placa:{placa}')
        conn.commit()
        flash(f'Vehículo {placa} actualizado.','success')
        conn.close(); return redirect(url_for('vehiculos'))
    cur.execute("SELECT * FROM TIPO_VEHICULO ORDER BY id_tipo")
    tipos = fetchall(cur)
    conn.close()
    return render_template('editar_vehiculo.html', veh=veh, tipos=tipos)

@app.route('/vehiculos/eliminar/<placa>', methods=['POST'])
@login_required
def eliminar_vehiculo(placa):
    conn = get_db(); cur = conn.cursor()
    cur.execute("SELECT * FROM VEHICULO WHERE placa=%s", (placa,))
    veh = fetchone(cur)
    if not veh:
        flash('Vehículo no encontrado.','danger'); conn.close(); return redirect(url_for('vehiculos'))
    if session['rol'] not in ('Administrador','Operario') and veh['id_usuario'] != session['user_id']:
        flash('Sin permisos.','danger'); conn.close(); return redirect(url_for('vehiculos'))
    cur.execute("SELECT COUNT(*) FROM REGISTRO_PARQUEO WHERE placa=%s AND estado='Abierto'", (placa,))
    if cur.fetchone()[0]:
        flash('No se puede eliminar: el vehículo está dentro del parqueadero.','danger')
        conn.close(); return redirect(url_for('vehiculos'))
    try:
        cur.execute("DELETE FROM VEHICULO WHERE placa=%s", (placa,))
        _log(cur, 'VEHICULO_ELIMINADO', f'Placa:{placa}')
        conn.commit()
        flash(f'Vehículo {placa} eliminado.','success')
    except Exception:
        conn.rollback()
        flash('No se puede eliminar: tiene historial de parqueos asociado.','danger')
    conn.close(); return redirect(url_for('vehiculos'))

@app.route('/usuarios/editar/<int:uid>', methods=['POST'])
@login_required
@role_required('Administrador')
def editar_usuario(uid):
    if uid == session['user_id']:
        flash('No puedes editar tu propio rol.','danger'); return redirect(url_for('usuarios'))
    id_rol = int(request.form['id_rol'])
    conn   = get_db(); cur = conn.cursor()
    cur.execute("UPDATE USUARIO SET id_rol=%s WHERE id_usuario=%s", (id_rol, uid))
    _log(cur, 'USUARIO_ROL_CAMBIADO', f'ID:{uid} → Rol:{id_rol}')
    conn.commit(); conn.close()
    flash('Rol actualizado.','success')
    return redirect(url_for('usuarios'))

# ── Inicializar BD al arrancar (funciona con gunicorn también) ─────────────────
with app.app_context():
    init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
