import os
from flask import Flask, jsonify
import xmlrpc.client
import pandas as pd
from datetime import datetime, timedelta

app = Flask(__name__)

# Tabla de BPM por tubo
BPM_TABLE = {
    14: 23,
    15: 23,
    16: 23,
    18: 23,
    19: 19,
    20: 19,
    21: 19,
    23: 19,
    500: 4,
    1: 0,
    0: 0,
    100: 3,
    101: 0.0083,
    102: 0.033,
    103: 0.016,
    104: 0.05,
    105: 0,
    2: 0
}

# Orígenes de máquinas
MACHINE_ORIGINS = ["MAQUINA 1", "MAQUINA 2", "MAQUINA 3", "MAQUINA 4", 
                   "MAQUINA 5", "MAQUINA 6", "MAQUINA 7", "GRANEL"]

# Estados válidos
VALID_STATES = ["draft", "confirmed", "progress", "to_close"]

# Ruta raíz para mostrar un mensaje de bienvenida
@app.route('/')
def home():
    return "Bienvenido a la API de planificación de producción"

# Ruta para obtener la planificación de bolsas para las próximas 8 horas
@app.route('/planificacion_8_horas', methods=['GET'])
def planificacion_8_horas():
    try:
        # Conexión y autenticación con Odoo usando variables de entorno
        url = os.getenv('ODOO_URL', 'https://erp.snackselvalle.com')
        db = os.getenv('DB', 'snackselvalle_fc0268f0')
        username = os.getenv('USUARIO', 'josemiruiz@snackselvalle.com')
        password = os.getenv('PASSWORD', '997523cee8dc70f78df1173b4507d994e0fdfd10')

        if not username or not password:
            return jsonify({'error': 'Las credenciales de Odoo no están configuradas correctamente en las variables de entorno'}), 500

        common = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/common')
        uid = common.authenticate(db, username, password, {})

        if not uid:
            return jsonify({'error': 'Error de autenticación'}), 403

        models = xmlrpc.client.ServerProxy(f'{url}/xmlrpc/2/object')

        # --- OBTENER ÓRDENES DE PRODUCCIÓN ---
        production_orders = models.execute_kw(
            db, uid, password,
            'mrp.production', 'search_read',
            [['&', ['state', 'in', VALID_STATES], ['origin', 'in', MACHINE_ORIGINS]]],
            {'fields': ['id', 'origin', 'product_id', 'product_qty', 'x_studio_peso_total', 'sequence'],
             'order': 'origin asc, sequence asc, id asc'}
        )

        if not production_orders:
            return jsonify({'message': 'No se encontraron órdenes de producción.'})

        # --- OBTENER INFORMACIÓN DE PRODUCTOS (TUBOS) ---
        product_ids = list(set([order['product_id'][0] for order in production_orders]))

        products_info = models.execute_kw(
            db, uid, password,
            'product.product', 'search_read',
            [[['id', 'in', product_ids]]],
            {'fields': ['id', 'name', 'tube']}
        )

        # Crear diccionario de productos con su tubo
        product_tube_map = {p['id']: p.get('tube', 0) for p in products_info}
        product_name_map = {p['id']: p['name'] for p in products_info}

        # --- AGRUPAR POR ORIGEN ---
        orders_by_origin = {}
        for origin in MACHINE_ORIGINS:
            orders_by_origin[origin] = []

        for order in production_orders:
            origin = order['origin']
            if origin in orders_by_origin:
                orders_by_origin[origin].append(order)

        # --- CALCULAR BOLSAS PARA 8 HORAS POR ORIGEN ---
        MAX_HOURS = 8
        results_by_origin = []
        total_bags_all_origins = 0

        for origin in MACHINE_ORIGINS:
            orders = orders_by_origin[origin]
            
            accumulated_hours = 0
            total_bags_origin = 0
            orders_detail = []
            
            for order in orders:
                product_id = order['product_id'][0]
                product_name = product_name_map.get(product_id, 'Desconocido')
                product_qty = order['product_qty']
                tube = product_tube_map.get(product_id, 0)
                bpm = BPM_TABLE.get(tube, 0)
                
                # Si BPM es 0, no se puede calcular
                if bpm == 0:
                    continue
                
                # Calcular tiempo para esta orden completa
                time_hours = product_qty / (bpm * 60)
                
                # Verificar si cabe completa en las 8 horas
                if accumulated_hours + time_hours <= MAX_HOURS:
                    # Cabe completa
                    bags_to_produce = product_qty
                    time_used = time_hours
                    accumulated_hours += time_hours
                elif accumulated_hours < MAX_HOURS:
                    # Cabe parcialmente, ajustar cantidad
                    remaining_hours = MAX_HOURS - accumulated_hours
                    bags_to_produce = remaining_hours * bpm * 60
                    time_used = remaining_hours
                    accumulated_hours = MAX_HOURS
                else:
                    # Ya se completaron las 8 horas
                    break
                
                total_bags_origin += bags_to_produce
                
                orders_detail.append({
                    'producto': product_name,
                    'tubo': tube,
                    'bpm': bpm,
                    'cantidad_original': round(product_qty, 2),
                    'bolsas_planificadas': round(bags_to_produce, 2),
                    'tiempo_horas': round(time_used, 2)
                })
                
                # Si ya llegamos a 8 horas, salir
                if accumulated_hours >= MAX_HOURS:
                    break
            
            # Agregar resultado de este origen
            results_by_origin.append({
                'origen': origin,
                'total_bolsas': round(total_bags_origin, 2),
                'tiempo_total_horas': round(accumulated_hours, 2),
                'detalle_ordenes': orders_detail
            })
            
            total_bags_all_origins += total_bags_origin

        # --- DEVOLVER RESULTADO EN JSON ---
        return jsonify({
            'por_origen': results_by_origin,
            'total_general': round(total_bags_all_origins, 2)
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Arranque de la aplicación Flask en Railway
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)