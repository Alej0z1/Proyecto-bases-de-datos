-- ============================================================
-- NEOPARK ECCI — Script SQL Tercera Entrega (Completo)
-- Temas: Consultas avanzadas, Seguridad, PL/SQL equivalente,
--        Procedimientos, Funciones, Triggers, Transacciones,
--        Concurrencia, Vistas
-- Motor: MySQL 8.x
-- Integrantes: Justin Infante · Jhon Guzmán · Alejandro Jiménez
-- Grupo 6 BNL — Universidad ECCI — Mayo 2026
-- ============================================================

DROP DATABASE IF EXISTS neopark_ecci;
CREATE DATABASE neopark_ecci
    CHARACTER SET utf8mb4
    COLLATE utf8mb4_unicode_ci;
USE neopark_ecci;

-- ============================================================
-- SECCIÓN 1: TABLAS BASE (modelo 7 tablas en 3FN)
-- ============================================================
CREATE TABLE ROL (
    id_rol      INT          NOT NULL AUTO_INCREMENT,
    nombre_rol  VARCHAR(30)  NOT NULL,
    descripcion VARCHAR(150) NOT NULL,
    CONSTRAINT pk_rol        PRIMARY KEY (id_rol),
    CONSTRAINT uq_rol_nombre UNIQUE (nombre_rol)
) ENGINE=InnoDB;

CREATE TABLE TIPO_VEHICULO (
    id_tipo     INT          NOT NULL AUTO_INCREMENT,
    nombre_tipo VARCHAR(30)  NOT NULL,
    descripcion VARCHAR(100) NULL,
    CONSTRAINT pk_tipo      PRIMARY KEY (id_tipo),
    CONSTRAINT uq_tipo_nombre UNIQUE (nombre_tipo)
) ENGINE=InnoDB;

CREATE TABLE USUARIO (
    id_usuario      INT          NOT NULL AUTO_INCREMENT,
    nombre          VARCHAR(80)  NOT NULL,
    apellido        VARCHAR(80)  NOT NULL,
    correo          VARCHAR(120) NOT NULL,
    contrasena_hash VARCHAR(255) NOT NULL,
    id_rol          INT          NOT NULL DEFAULT 3,
    activo          TINYINT(1)   NOT NULL DEFAULT 1,
    fecha_registro  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_usuario         PRIMARY KEY (id_usuario),
    CONSTRAINT uq_usuario_correo  UNIQUE (correo),
    CONSTRAINT fk_usuario_rol     FOREIGN KEY (id_rol) REFERENCES ROL(id_rol) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_correo         CHECK (correo LIKE '%@ecci.edu.co')
) ENGINE=InnoDB;

CREATE TABLE VEHICULO (
    placa      VARCHAR(10) NOT NULL,
    id_tipo    INT         NOT NULL,
    marca      VARCHAR(50) NULL,
    modelo     VARCHAR(50) NULL,
    color      VARCHAR(30) NULL,
    id_usuario INT         NOT NULL,
    CONSTRAINT pk_vehiculo         PRIMARY KEY (placa),
    CONSTRAINT fk_vehiculo_tipo    FOREIGN KEY (id_tipo)    REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_vehiculo_usuario FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario)    ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE ESPACIO (
    id_espacio INTEGER     NOT NULL AUTO_INCREMENT,
    codigo     VARCHAR(10) NOT NULL,
    id_tipo    INT         NOT NULL,
    disponible TINYINT(1)  NOT NULL DEFAULT 1,
    CONSTRAINT pk_espacio       PRIMARY KEY (id_espacio),
    CONSTRAINT uq_espacio_codigo UNIQUE (codigo),
    CONSTRAINT fk_espacio_tipo  FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB;

CREATE TABLE TARIFA (
    id_tarifa        INT            NOT NULL AUTO_INCREMENT,
    id_tipo          INT            NOT NULL,
    valor_por_hora   DECIMAL(10,2)  NOT NULL,
    fraccion_minutos INT            NOT NULL DEFAULT 15,
    activo           TINYINT(1)     NOT NULL DEFAULT 1,
    fecha_vigencia   DATE           NOT NULL,
    CONSTRAINT pk_tarifa              PRIMARY KEY (id_tarifa),
    CONSTRAINT uq_tarifa_tipo_fecha   UNIQUE (id_tipo, fecha_vigencia),
    CONSTRAINT fk_tarifa_tipo         FOREIGN KEY (id_tipo) REFERENCES TIPO_VEHICULO(id_tipo) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_valor_positivo     CHECK (valor_por_hora > 0),
    CONSTRAINT chk_fraccion_positiva  CHECK (fraccion_minutos > 0)
) ENGINE=InnoDB;

CREATE TABLE REGISTRO_PARQUEO (
    id_registro   INT            NOT NULL AUTO_INCREMENT,
    placa         VARCHAR(10)    NOT NULL,
    id_espacio    INT            NOT NULL,
    fecha_entrada DATE           NOT NULL,
    hora_entrada  TIME           NOT NULL,
    fecha_salida  DATE           NULL,
    hora_salida   TIME           NULL,
    valor_pagado  DECIMAL(10,2)  NULL,
    estado        ENUM('Abierto','Cerrado') NOT NULL DEFAULT 'Abierto',
    CONSTRAINT pk_registro          PRIMARY KEY (id_registro),
    CONSTRAINT fk_registro_vehiculo FOREIGN KEY (placa)       REFERENCES VEHICULO(placa)     ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_registro_espacio  FOREIGN KEY (id_espacio)  REFERENCES ESPACIO(id_espacio) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT chk_fecha_coherente  CHECK (fecha_salida IS NULL OR fecha_salida >= fecha_entrada),
    CONSTRAINT chk_valor_cobro      CHECK (valor_pagado IS NULL OR valor_pagado >= 0)
) ENGINE=InnoDB;

CREATE TABLE AUDITORIA (
    id_auditoria INT          NOT NULL AUTO_INCREMENT,
    id_usuario   INT          NOT NULL,
    accion       VARCHAR(50)  NOT NULL,
    detalle      TEXT         NULL,
    ip           VARCHAR(45)  NULL,
    fecha_hora   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT pk_auditoria        PRIMARY KEY (id_auditoria),
    CONSTRAINT fk_auditoria_usuario FOREIGN KEY (id_usuario) REFERENCES USUARIO(id_usuario) ON DELETE RESTRICT
) ENGINE=InnoDB;

-- ============================================================
-- SECCIÓN 2: VISTAS
-- ============================================================

-- Vista: ocupación actual del parqueadero
CREATE OR REPLACE VIEW V_OCUPACION_ACTUAL AS
SELECT
    e.id_espacio,
    e.codigo,
    tv.nombre_tipo,
    CASE WHEN e.disponible = 1 THEN 'Libre' ELSE 'Ocupado' END AS estado,
    r.placa,
    r.fecha_entrada,
    r.hora_entrada,
    u.nombre AS propietario_nombre,
    u.apellido AS propietario_apellido,
    TIMESTAMPDIFF(MINUTE,
        TIMESTAMP(r.fecha_entrada, r.hora_entrada),
        NOW()
    ) AS minutos_transcurridos
FROM ESPACIO e
JOIN TIPO_VEHICULO tv ON e.id_tipo = tv.id_tipo
LEFT JOIN REGISTRO_PARQUEO r ON r.id_espacio = e.id_espacio AND r.estado = 'Abierto'
LEFT JOIN VEHICULO v ON r.placa = v.placa
LEFT JOIN USUARIO u ON v.id_usuario = u.id_usuario;

-- Vista: resumen de recaudo por tipo de vehículo
CREATE OR REPLACE VIEW V_RECAUDO_POR_TIPO AS
SELECT
    tv.nombre_tipo,
    COUNT(r.id_registro)          AS total_registros,
    SUM(r.valor_pagado)           AS recaudo_total,
    AVG(r.valor_pagado)           AS recaudo_promedio,
    MAX(r.valor_pagado)           AS recaudo_maximo,
    AVG(TIMESTAMPDIFF(MINUTE,
        TIMESTAMP(r.fecha_entrada, r.hora_entrada),
        TIMESTAMP(r.fecha_salida, r.hora_salida)
    ))                            AS minutos_promedio_estadia
FROM REGISTRO_PARQUEO r
JOIN VEHICULO v ON r.placa = v.placa
JOIN TIPO_VEHICULO tv ON v.id_tipo = tv.id_tipo
WHERE r.estado = 'Cerrado'
GROUP BY tv.id_tipo, tv.nombre_tipo;

-- Vista: historial completo con datos enriquecidos
CREATE OR REPLACE VIEW V_HISTORIAL_COMPLETO AS
SELECT
    r.id_registro,
    r.placa,
    tv.nombre_tipo,
    e.codigo AS espacio,
    u.nombre AS propietario_nombre,
    u.apellido AS propietario_apellido,
    u.correo AS propietario_correo,
    r.fecha_entrada,
    r.hora_entrada,
    r.fecha_salida,
    r.hora_salida,
    r.valor_pagado,
    r.estado,
    TIMESTAMPDIFF(MINUTE,
        TIMESTAMP(r.fecha_entrada, r.hora_entrada),
        IFNULL(TIMESTAMP(r.fecha_salida, r.hora_salida), NOW())
    ) AS minutos_total,
    t.valor_por_hora AS tarifa_aplicada
FROM REGISTRO_PARQUEO r
JOIN VEHICULO v ON r.placa = v.placa
JOIN TIPO_VEHICULO tv ON v.id_tipo = tv.id_tipo
JOIN ESPACIO e ON r.id_espacio = e.id_espacio
JOIN USUARIO u ON v.id_usuario = u.id_usuario
LEFT JOIN TARIFA t ON t.id_tipo = v.id_tipo AND t.activo = 1;

-- Vista: disponibilidad resumida por tipo
CREATE OR REPLACE VIEW V_DISPONIBILIDAD_TIPO AS
SELECT
    tv.nombre_tipo,
    COUNT(e.id_espacio)                                        AS total_espacios,
    SUM(e.disponible)                                          AS espacios_libres,
    SUM(1 - e.disponible)                                      AS espacios_ocupados,
    ROUND(SUM(1 - e.disponible) / COUNT(e.id_espacio) * 100, 1) AS porcentaje_ocupacion
FROM ESPACIO e
JOIN TIPO_VEHICULO tv ON e.id_tipo = tv.id_tipo
GROUP BY tv.id_tipo, tv.nombre_tipo;

-- ============================================================
-- SECCIÓN 3: FUNCIONES ALMACENADAS
-- ============================================================
DELIMITER $$

-- Función: calcular valor a pagar dado tipo de vehículo y minutos
CREATE FUNCTION fn_calcular_cobro(
    p_id_tipo        INT,
    p_minutos        INT
) RETURNS DECIMAL(10,2)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_valor_hora   DECIMAL(10,2) DEFAULT 0;
    DECLARE v_fraccion     INT           DEFAULT 15;
    DECLARE v_fracciones   INT           DEFAULT 0;
    DECLARE v_cobro        DECIMAL(10,2) DEFAULT 0;

    SELECT valor_por_hora, fraccion_minutos
    INTO   v_valor_hora, v_fraccion
    FROM   TARIFA
    WHERE  id_tipo = p_id_tipo AND activo = 1
    ORDER  BY fecha_vigencia DESC
    LIMIT  1;

    IF v_valor_hora = 0 OR p_minutos <= 0 THEN
        RETURN 0;
    END IF;

    SET v_fracciones = CEIL(p_minutos / v_fraccion);
    SET v_cobro = v_fracciones * (v_valor_hora / (60 / v_fraccion));

    RETURN ROUND(v_cobro, 0);
END$$

-- Función: obtener estado de ocupación del parqueadero
CREATE FUNCTION fn_estado_parqueadero(
    p_id_tipo INT
) RETURNS VARCHAR(20)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_libres INT DEFAULT 0;

    SELECT COUNT(*) INTO v_libres
    FROM   ESPACIO
    WHERE  id_tipo = p_id_tipo AND disponible = 1;

    IF v_libres = 0 THEN
        RETURN 'OCUPACION_TOTAL';
    ELSEIF v_libres <= 2 THEN
        RETURN 'CASI_LLENO';
    ELSE
        RETURN 'DISPONIBLE';
    END IF;
END$$

-- Función: verificar si usuario tiene vehículo activo
CREATE FUNCTION fn_usuario_tiene_activo(
    p_id_usuario INT
) RETURNS TINYINT(1)
DETERMINISTIC
READS SQL DATA
BEGIN
    DECLARE v_count INT DEFAULT 0;

    SELECT COUNT(*) INTO v_count
    FROM   REGISTRO_PARQUEO r
    JOIN   VEHICULO v ON r.placa = v.placa
    WHERE  v.id_usuario = p_id_usuario AND r.estado = 'Abierto';

    RETURN IF(v_count > 0, 1, 0);
END$$

-- Función: calcular minutos entre dos timestamps
CREATE FUNCTION fn_minutos_transcurridos(
    p_fecha_entrada DATE,
    p_hora_entrada  TIME
) RETURNS INT
DETERMINISTIC
NO SQL
BEGIN
    RETURN TIMESTAMPDIFF(MINUTE,
        TIMESTAMP(p_fecha_entrada, p_hora_entrada),
        NOW()
    );
END$$

DELIMITER ;

-- ============================================================
-- SECCIÓN 4: PROCEDIMIENTOS ALMACENADOS
-- ============================================================
DELIMITER $$

-- Procedimiento: registrar entrada (check-in) con transacción
CREATE PROCEDURE sp_checkin(
    IN  p_placa      VARCHAR(10),
    IN  p_id_usuario INT,
    OUT p_resultado  VARCHAR(100),
    OUT p_espacio    VARCHAR(10)
)
BEGIN
    DECLARE v_id_tipo    INT;
    DECLARE v_id_espacio INT;
    DECLARE v_codigo     VARCHAR(10);
    DECLARE v_tiene_activo TINYINT(1);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_resultado = 'ERROR: Fallo inesperado en la transacción';
        SET p_espacio   = NULL;
    END;

    START TRANSACTION;

    -- Verificar vehículo registrado (RN1)
    SELECT id_tipo INTO v_id_tipo FROM VEHICULO WHERE placa = p_placa;
    IF v_id_tipo IS NULL THEN
        ROLLBACK;
        SET p_resultado = 'ERROR_RN1: Vehículo no registrado';
        SET p_espacio = NULL;
        LEAVE sp_checkin;
    END IF;

    -- Verificar RN2: usuario sin vehículo activo (con SELECT FOR UPDATE para concurrencia)
    SELECT fn_usuario_tiene_activo(p_id_usuario) INTO v_tiene_activo;
    IF v_tiene_activo = 1 THEN
        ROLLBACK;
        SET p_resultado = 'ERROR_RN2: Propietario ya tiene vehículo dentro';
        SET p_espacio = NULL;
        LEAVE sp_checkin;
    END IF;

    -- Asignar espacio libre con bloqueo (SELECT FOR UPDATE = control de concurrencia)
    SELECT id_espacio, codigo INTO v_id_espacio, v_codigo
    FROM   ESPACIO
    WHERE  id_tipo = v_id_tipo AND disponible = 1
    LIMIT  1
    FOR UPDATE;

    -- Verificar RN4: ocupación total
    IF v_id_espacio IS NULL THEN
        ROLLBACK;
        SET p_resultado = CONCAT('ERROR_RN4: Ocupación total para ', fn_estado_parqueadero(v_id_tipo));
        SET p_espacio = NULL;
        LEAVE sp_checkin;
    END IF;

    -- Registrar entrada
    INSERT INTO REGISTRO_PARQUEO (placa, id_espacio, fecha_entrada, hora_entrada, estado)
    VALUES (p_placa, v_id_espacio, CURDATE(), CURTIME(), 'Abierto');

    -- Marcar espacio como ocupado
    UPDATE ESPACIO SET disponible = 0 WHERE id_espacio = v_id_espacio;

    COMMIT;

    SET p_resultado = CONCAT('OK: Check-in exitoso');
    SET p_espacio   = v_codigo;
END$$

-- Procedimiento: registrar salida (check-out) con transacción
CREATE PROCEDURE sp_checkout(
    IN  p_id_registro INT,
    OUT p_resultado   VARCHAR(100),
    OUT p_valor       DECIMAL(10,2)
)
BEGIN
    DECLARE v_placa       VARCHAR(10);
    DECLARE v_id_espacio  INT;
    DECLARE v_id_tipo     INT;
    DECLARE v_fecha_e     DATE;
    DECLARE v_hora_e      TIME;
    DECLARE v_minutos     INT;
    DECLARE v_valor       DECIMAL(10,2);
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_resultado = 'ERROR: Fallo en la transacción de checkout';
        SET p_valor = 0;
    END;

    START TRANSACTION;

    -- Obtener datos del registro con bloqueo
    SELECT placa, id_espacio, fecha_entrada, hora_entrada
    INTO   v_placa, v_id_espacio, v_fecha_e, v_hora_e
    FROM   REGISTRO_PARQUEO
    WHERE  id_registro = p_id_registro AND estado = 'Abierto'
    FOR UPDATE;

    IF v_placa IS NULL THEN
        ROLLBACK;
        SET p_resultado = 'ERROR: Registro no encontrado o ya cerrado';
        SET p_valor = 0;
        LEAVE sp_checkout;
    END IF;

    -- Obtener tipo de vehículo
    SELECT id_tipo INTO v_id_tipo FROM VEHICULO WHERE placa = v_placa;

    -- Calcular minutos transcurridos
    SET v_minutos = fn_minutos_transcurridos(v_fecha_e, v_hora_e);

    -- Calcular cobro usando la función
    SET v_valor = fn_calcular_cobro(v_id_tipo, v_minutos);

    -- Cerrar registro
    UPDATE REGISTRO_PARQUEO
    SET    fecha_salida  = CURDATE(),
           hora_salida   = CURTIME(),
           valor_pagado  = v_valor,
           estado        = 'Cerrado'
    WHERE  id_registro   = p_id_registro;

    -- Liberar espacio
    UPDATE ESPACIO SET disponible = 1 WHERE id_espacio = v_id_espacio;

    COMMIT;

    SET p_resultado = 'OK: Checkout completado';
    SET p_valor = v_valor;
END$$

-- Procedimiento: reporte de recaudo por período
CREATE PROCEDURE sp_reporte_recaudo(
    IN p_fecha_inicio DATE,
    IN p_fecha_fin    DATE
)
BEGIN
    SELECT
        tv.nombre_tipo                          AS tipo_vehiculo,
        COUNT(r.id_registro)                    AS total_registros,
        SUM(r.valor_pagado)                     AS recaudo_total,
        ROUND(AVG(r.valor_pagado), 0)           AS promedio_cobro,
        ROUND(AVG(TIMESTAMPDIFF(MINUTE,
            TIMESTAMP(r.fecha_entrada, r.hora_entrada),
            TIMESTAMP(r.fecha_salida, r.hora_salida)
        )), 0)                                  AS minutos_promedio
    FROM REGISTRO_PARQUEO r
    JOIN VEHICULO v ON r.placa = v.placa
    JOIN TIPO_VEHICULO tv ON v.id_tipo = tv.id_tipo
    WHERE r.estado = 'Cerrado'
      AND r.fecha_salida BETWEEN p_fecha_inicio AND p_fecha_fin
    GROUP BY tv.id_tipo, tv.nombre_tipo
    ORDER BY recaudo_total DESC;
END$$

-- Procedimiento: actualizar tarifa desactivando la anterior
CREATE PROCEDURE sp_actualizar_tarifa(
    IN  p_id_tipo        INT,
    IN  p_valor_hora     DECIMAL(10,2),
    IN  p_fraccion_min   INT,
    OUT p_resultado      VARCHAR(100)
)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        SET p_resultado = 'ERROR: No se pudo actualizar la tarifa';
    END;

    IF p_valor_hora <= 0 THEN
        SET p_resultado = 'ERROR: El valor por hora debe ser mayor a 0';
        LEAVE sp_actualizar_tarifa;
    END IF;

    START TRANSACTION;

    UPDATE TARIFA SET activo = 0 WHERE id_tipo = p_id_tipo;

    INSERT INTO TARIFA (id_tipo, valor_por_hora, fraccion_minutos, activo, fecha_vigencia)
    VALUES (p_id_tipo, p_valor_hora, p_fraccion_min, 1, CURDATE());

    COMMIT;

    SET p_resultado = CONCAT('OK: Tarifa actualizada a $', p_valor_hora, '/hora');
END$$

DELIMITER ;

-- ============================================================
-- SECCIÓN 5: TRIGGERS
-- ============================================================
DELIMITER $$

-- Trigger: BEFORE INSERT en REGISTRO_PARQUEO
-- Valida reglas de negocio antes de insertar
CREATE TRIGGER trg_checkin_validar
BEFORE INSERT ON REGISTRO_PARQUEO
FOR EACH ROW
BEGIN
    DECLARE v_id_usuario INT;
    DECLARE v_tiene_activo INT;
    DECLARE v_disponible INT;

    -- Obtener propietario del vehículo
    SELECT id_usuario INTO v_id_usuario FROM VEHICULO WHERE placa = NEW.placa;

    -- RN2: verificar que el propietario no tenga otro vehículo activo
    SELECT COUNT(*) INTO v_tiene_activo
    FROM   REGISTRO_PARQUEO rp
    JOIN   VEHICULO v ON rp.placa = v.placa
    WHERE  v.id_usuario = v_id_usuario AND rp.estado = 'Abierto';

    IF v_tiene_activo > 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'RN2: El usuario ya tiene un vehículo activo dentro del parqueadero';
    END IF;

    -- RN4: verificar que el espacio esté disponible
    SELECT disponible INTO v_disponible FROM ESPACIO WHERE id_espacio = NEW.id_espacio;

    IF v_disponible = 0 THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'RN4: El espacio seleccionado ya está ocupado';
    END IF;
END$$

-- Trigger: AFTER INSERT en REGISTRO_PARQUEO
-- Automáticamente marca el espacio como ocupado
CREATE TRIGGER trg_checkin_marcar_espacio
AFTER INSERT ON REGISTRO_PARQUEO
FOR EACH ROW
BEGIN
    IF NEW.estado = 'Abierto' THEN
        UPDATE ESPACIO SET disponible = 0 WHERE id_espacio = NEW.id_espacio;
    END IF;
END$$

-- Trigger: AFTER UPDATE en REGISTRO_PARQUEO
-- Al cerrar el registro, libera el espacio automáticamente
CREATE TRIGGER trg_checkout_liberar_espacio
AFTER UPDATE ON REGISTRO_PARQUEO
FOR EACH ROW
BEGIN
    IF OLD.estado = 'Abierto' AND NEW.estado = 'Cerrado' THEN
        UPDATE ESPACIO SET disponible = 1 WHERE id_espacio = NEW.id_espacio;
    END IF;
END$$

-- Trigger: BEFORE UPDATE en REGISTRO_PARQUEO
-- Valida que la hora de salida sea posterior a la de entrada
CREATE TRIGGER trg_checkout_validar_hora
BEFORE UPDATE ON REGISTRO_PARQUEO
FOR EACH ROW
BEGIN
    IF NEW.estado = 'Cerrado' AND NEW.fecha_salida IS NOT NULL THEN
        IF TIMESTAMP(NEW.fecha_salida, NEW.hora_salida) <=
           TIMESTAMP(NEW.fecha_entrada, NEW.hora_entrada) THEN
            SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'La hora de salida debe ser posterior a la hora de entrada';
        END IF;
    END IF;
END$$

-- Trigger: BEFORE INSERT en USUARIO
-- Normaliza el correo a minúsculas
CREATE TRIGGER trg_usuario_normalizar_correo
BEFORE INSERT ON USUARIO
FOR EACH ROW
BEGIN
    SET NEW.correo = LOWER(TRIM(NEW.correo));
    IF NEW.correo NOT LIKE '%@ecci.edu.co' THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'El correo debe ser institucional @ecci.edu.co';
    END IF;
END$$

-- Trigger: BEFORE UPDATE en TARIFA
-- Impide modificar tarifas ya usadas en registros históricos
CREATE TRIGGER trg_tarifa_proteger_historico
BEFORE UPDATE ON TARIFA
FOR EACH ROW
BEGIN
    DECLARE v_usos INT;

    SELECT COUNT(*) INTO v_usos
    FROM   REGISTRO_PARQUEO r
    JOIN   VEHICULO v ON r.placa = v.placa
    WHERE  v.id_tipo = OLD.id_tipo AND r.estado = 'Cerrado';

    IF v_usos > 0 AND OLD.valor_por_hora != NEW.valor_por_hora THEN
        SIGNAL SQLSTATE '45000'
        SET MESSAGE_TEXT = 'No se puede modificar el valor de una tarifa con registros históricos. Use sp_actualizar_tarifa para crear nueva vigencia.';
    END IF;
END$$

DELIMITER ;

-- ============================================================
-- SECCIÓN 6: SEGURIDAD — Usuarios de BD con permisos
-- ============================================================

CREATE USER IF NOT EXISTS 'neopark_admin'@'localhost'    IDENTIFIED BY 'Admin@NeoPark2026!';
CREATE USER IF NOT EXISTS 'neopark_operario'@'localhost' IDENTIFIED BY 'Op3rario@2026!';
CREATE USER IF NOT EXISTS 'neopark_reporte'@'localhost'  IDENTIFIED BY 'R3port@2026!';

GRANT ALL PRIVILEGES ON neopark_ecci.* TO 'neopark_admin'@'localhost';

GRANT SELECT, INSERT, UPDATE ON neopark_ecci.REGISTRO_PARQUEO TO 'neopark_operario'@'localhost';
GRANT SELECT, UPDATE         ON neopark_ecci.ESPACIO           TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.VEHICULO          TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.USUARIO           TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.TARIFA            TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.TIPO_VEHICULO     TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.ROL               TO 'neopark_operario'@'localhost';
GRANT SELECT                 ON neopark_ecci.V_OCUPACION_ACTUAL TO 'neopark_operario'@'localhost';
GRANT EXECUTE                ON PROCEDURE neopark_ecci.sp_checkin  TO 'neopark_operario'@'localhost';
GRANT EXECUTE                ON PROCEDURE neopark_ecci.sp_checkout TO 'neopark_operario'@'localhost';

GRANT SELECT ON neopark_ecci.* TO 'neopark_reporte'@'localhost';

FLUSH PRIVILEGES;

-- ============================================================
-- SECCIÓN 7: DATOS DE PRUEBA
-- ============================================================

INSERT INTO ROL (nombre_rol, descripcion) VALUES
('Administrador', 'Acceso total: tarifas, usuarios, reportes, configuración'),
('Operario',      'Registro de entradas y salidas de vehículos'),
('Usuario',       'Consulta de disponibilidad e historial personal'),
('Auditor',       'Solo lectura para revisión de registros históricos'),
('Supervisor',    'Supervisión de operarios y acceso a reportes parciales');

INSERT INTO TIPO_VEHICULO (nombre_tipo, descripcion) VALUES
('Carro',     'Automóvil de cuatro ruedas: sedán, campero, camioneta'),
('Moto',      'Motocicleta de dos ruedas de cualquier cilindraje'),
('Bicicleta', 'Vehículo de dos ruedas no motorizado'),
('Camioneta', 'Vehículo de carga liviana tipo pick-up o van'),
('Patineta',  'Vehículo de movilidad personal no motorizado');

-- Contraseñas: Admin123!, Op123!, User123! (SHA-256)
INSERT INTO USUARIO (nombre, apellido, correo, contrasena_hash, id_rol) VALUES
('Justin',    'Infante',   'justisfe.infantecristancho@ecci.edu.co', SHA2('Admin123!',256), 1),
('Jhon',      'Guzmán',    'jhone.guzmansalinas@ecci.edu.co',         SHA2('Op123!',256),    2),
('Alejandro', 'Jiménez',   'alejoe.jimenezperez@ecci.edu.co',        SHA2('User123!',256),  3),
('Carlos',    'Rodríguez', 'c.rodriguez@ecci.edu.co',                SHA2('User123!',256),  3),
('María',     'López',     'm.lopez@ecci.edu.co',                    SHA2('User123!',256),  3);

INSERT INTO VEHICULO (placa, id_tipo, marca, modelo, color, id_usuario) VALUES
('ABC123', 1, 'Chevrolet', 'Spark',  'Blanco', 3),
('XYZ789', 2, 'Honda',     'CBR150', 'Negro',  4),
('QWE456', 1, 'Renault',   'Logan',  'Gris',   5),
('MNO321', 3, NULL,        NULL,     'Azul',   3),
('PQR654', 2, 'Yamaha',    'FZ16',   'Rojo',   5);

INSERT INTO ESPACIO (codigo, id_tipo, disponible) VALUES
('C-01',1,0),('C-02',1,1),('C-03',1,1),('C-04',1,1),('C-05',1,1),
('C-06',1,1),('C-07',1,1),('C-08',1,1),('C-09',1,1),('C-10',1,1),
('M-01',2,0),('M-02',2,1),('M-03',2,1),('M-04',2,1),('M-05',2,1),
('M-06',2,1),('M-07',2,1),('M-08',2,1),
('B-01',3,1),('B-02',3,1),('B-03',3,1),('B-04',3,1),('B-05',3,1);

INSERT INTO TARIFA (id_tipo, valor_por_hora, fraccion_minutos, activo, fecha_vigencia) VALUES
(1, 3000.00, 15, 1, '2026-01-01'),
(2, 2000.00, 15, 1, '2026-01-01'),
(3,  500.00, 60, 1, '2026-01-01'),
(1, 3500.00, 15, 0, '2025-01-01'),
(2, 2500.00, 15, 0, '2025-01-01');

-- Registros históricos sin trigger (INSERT directo con estado Cerrado)
INSERT INTO REGISTRO_PARQUEO (placa,id_espacio,fecha_entrada,hora_entrada,fecha_salida,hora_salida,valor_pagado,estado) VALUES
('QWE456',2,'2026-05-18','09:00:00','2026-05-18','12:00:00',9000,'Cerrado'),
('MNO321',7,'2026-05-17','07:15:00','2026-05-17','17:00:00',5000,'Cerrado'),
('PQR654',5,'2026-05-16','10:00:00','2026-05-16','11:30:00',3000,'Cerrado'),
('XYZ789',4,'2026-05-15','08:00:00','2026-05-15','10:00:00',4000,'Cerrado'),
('ABC123',1,'2026-05-14','07:30:00','2026-05-14','18:00:00',15000,'Cerrado');

-- Registros abiertos actuales (el trigger trg_checkin_marcar_espacio actualiza ESPACIO)
INSERT INTO REGISTRO_PARQUEO (placa,id_espacio,fecha_entrada,hora_entrada,estado) VALUES
('ABC123',1,CURDATE(),CURTIME(),'Abierto'),
('XYZ789',4,CURDATE(),CURTIME(),'Abierto');

-- ============================================================
-- SECCIÓN 8: CONSULTAS AVANZADAS DE DEMOSTRACIÓN
-- ============================================================

-- Q1: Usar la función fn_calcular_cobro directamente
-- SELECT fn_calcular_cobro(1, 90) AS cobro_90_minutos_carro;

-- Q2: Usar el procedimiento sp_reporte_recaudo
-- CALL sp_reporte_recaudo('2026-05-01', '2026-05-31');

-- Q3: Consultar la vista de ocupación actual
-- SELECT * FROM V_OCUPACION_ACTUAL;

-- Q4: Consulta con subconsulta correlacionada — vehículos con más de 1 visita
-- SELECT placa, COUNT(*) as visitas FROM REGISTRO_PARQUEO GROUP BY placa HAVING visitas > 1;

-- Q5: Uso explícito de transacción con SAVEPOINT
-- START TRANSACTION;
-- SAVEPOINT sp1;
-- CALL sp_checkin('QWE456', 5, @res, @esp);
-- SELECT @res, @esp;
-- ROLLBACK TO SAVEPOINT sp1;  -- revertir si hay error
-- COMMIT;

-- Q6: Verificar función de estado
-- SELECT fn_estado_parqueadero(1) AS estado_carros;

-- Q7: Consulta compleja — ranking de usuarios por recaudo generado
-- SELECT u.nombre, u.apellido, COUNT(r.id_registro) as visitas,
--        SUM(r.valor_pagado) as total_pagado
-- FROM USUARIO u JOIN VEHICULO v ON u.id_usuario=v.id_usuario
-- JOIN REGISTRO_PARQUEO r ON v.placa=r.placa
-- WHERE r.estado='Cerrado'
-- GROUP BY u.id_usuario ORDER BY total_pagado DESC;
