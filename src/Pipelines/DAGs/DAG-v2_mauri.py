# Librerias
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.dummy import DummyOperator
from datetime import timedelta
from airflow.utils.dates import days_ago
from google.cloud import bigquery

# Funciones
from functions.v2_registrar_archivo import registrar_archivos_procesados
from functions.v2_desanidar_misc import desanidar_misc
from functions.tabla_temporal import crear_tabla_temporal, cargar_archivo_en_tabla_temporal, mover_datos_y_borrar_temp

######################################################################################
# PARÁMETROS
######################################################################################

nameDAG_base      = 'ETL_Storage_to_BQ'
project_id        = 'neon-gist-439401-k8'
dataset           = '1'
owner             = 'Mauricio Arce'
GBQ_CONNECTION_ID = 'bigquery_default'
bucket_name       = 'datos-crudos'
prefix            = 'g_sitios/'
# Por ahora haremos prueba piloto para una sola columna con una sola tabla (misc)
temp_table        = 'miscelaneo' # Aqui deberian crearse 3 tablas temporales que son las columnas desanidadas del archivo ingresado (misc,relative_results,hours).
final_table       = 'g_misc' # Aqui deberian enviarse cada columna desanidada a su tabla final (g_misc,g_relative_results,g_hours)

default_args = {
    'owner': owner,
    'start_date': days_ago(1),
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

temp_table_schema = [
    bigquery.SchemaField("name", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("address", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("gmap_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("description", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("latitude", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("longitude", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("category", "STRING", mode="REPEATED"),  # Asume una lista de strings
    bigquery.SchemaField("avg_rating", "FLOAT", mode="NULLABLE"),
    bigquery.SchemaField("num_of_reviews", "INTEGER", mode="NULLABLE"),
    bigquery.SchemaField("price", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("hours", "STRING", mode="NULLABLE"),     # Almacena las horas como texto JSON
    bigquery.SchemaField("MISC", "STRING", mode="NULLABLE"),      # Almacena MISC como texto JSON
    bigquery.SchemaField("state", "STRING", mode="NULLABLE"),
    bigquery.SchemaField("relative_results", "STRING", mode="NULLABLE"),  # Almacena como texto JSON
    bigquery.SchemaField("url", "STRING", mode="NULLABLE"),
]


# Definir el esquema de la tabla temporal (aqui se deberria definir las columnas de las 3 tablas temporales.) Por ahora solo de miscelaneo.
temp_table_schema = [
    bigquery.SchemaField("gmap_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("misc", "STRING", mode="NULLABLE"),
]

#######################################################################################
# DEFINICIÓN DEL DAG
#######################################################################################

with DAG(
    dag_id=nameDAG_base,
    default_args=default_args,
    schedule_interval=None,
    catchup=False
) as dag:

    inicio = DummyOperator(task_id='inicio')

    # Tarea 1: Registrar archivos en una tabla que controlara cuales ya fueron procesados y cuales no.
    registrar_archivos = PythonOperator(
        task_id='registrar_archivos_procesados',
        python_callable=registrar_archivos_procesados,
        op_kwargs={
            'bucket_name': bucket_name,
            'prefix': prefix,
            'project_id': project_id,
            'dataset': dataset
        }
    )

    # Tarea 2: Crear la tabla temporal en BigQuery de cada columna anidada.
    crear_tabla_temp = PythonOperator(
        task_id='crear_tabla_temporal',
        python_callable=crear_tabla_temporal,
        op_kwargs={
            'project_id': project_id,
            'dataset': dataset,
            'temp_table': temp_table,
            'schema': temp_table_schema  # Pasa el esquema definido en el DAG
        }
    )

    # Tarea 3: Cargar el archivo JSON en la tabla temporal
    cargar_archivo_temp_task = PythonOperator(
        task_id='cargar_archivo_en_tabla_temporal',
        python_callable=cargar_archivo_en_tabla_temporal,
        op_kwargs={
            'bucket_name': bucket_name,
            'archivo': "{{ ti.xcom_pull(task_ids='registrar_archivos_procesados') }}",
            'project_id': project_id,
            'dataset': dataset,
            'temp_table': temp_table
        }
    )

    # Tarea 4: Desanidar misc y procesar el archivo en la tabla temporal
    procesar_misc_task = PythonOperator(
        task_id='desanidar_misc',
        python_callable=desanidar_misc,
        op_kwargs={
            'bucket_name': bucket_name,
            'archivo': "{{ ti.xcom_pull(task_ids='registrar_archivos_procesados') }}",
            'project_id': project_id,
            'dataset': dataset,
            'temp_table': temp_table  # Procesar en la tabla temporal
        }
    )


    # Tarea 5: Mover datos de la tabla temporal a la final y eliminar la temporal
    mover_datos_y_borrar_temp_task = PythonOperator(
        task_id='mover_datos_y_borrar_temp',
        python_callable=mover_datos_y_borrar_temp,
        op_kwargs={
            'project_id': project_id,
            'dataset': dataset,
            'temp_table': temp_table,
            'final_table': final_table
        }
    )

    fin = DummyOperator(task_id='fin')

    # Estructura del flujo de tareas
    inicio >> registrar_archivos >> crear_tabla_temp >> procesar_misc_task >> mover_datos_y_borrar_temp_task >> fin
