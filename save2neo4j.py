import math
import geopandas as gpd
from neo4j import GraphDatabase
from pyproj import Transformer

# Ścieżka do pliku SHP
shp_path = r"SKJZ.shp"

# Wczytaj plik SHP
gdf = gpd.read_file(shp_path)

# Przekształcenie CRS
gdf = gdf.to_crs(epsg=2180)

# Tworzenie punktów początkowych i końcowych
gdf['start_point'] = gdf['geometry'].apply(lambda geom: geom.coords[0])
gdf['end_point'] = gdf['geometry'].apply(lambda geom: geom.coords[-1])

# Unikalne wierzchołki (punkty)
nodes = set(gdf['start_point']).union(set(gdf['end_point']))

# Tworzenie listy krawędzi z atrybutami
edges = gdf[['start_point', 'end_point', 'klasaDrogi', 'kierunek', 'Shape_Leng']]

uri = "bolt://localhost:7687"
username = "neo4j"
password = "Baza1234"
database_name = "neo4j"

driver = GraphDatabase.driver(uri, auth=(username, password))

# Konwerter z EPSG:2180 (PUWG 1992) do EPSG:4326 (WGS 84)
transformer = Transformer.from_crs("EPSG:2180", "EPSG:4326", always_xy=True)

def convert_to_wgs84(x, y):
    lon, lat = transformer.transform(x, y)
    return round(lon, 4), round(lat, 4)  

def speed(klasa):
    kmh2ms = 1000 / 3600
    if klasa == 'A': # autostrada
        return 140 * kmh2ms
    elif klasa == 'S': # droga ekspresowa
        return 120 * kmh2ms
    elif klasa == 'GP': # główna ruchu
        return 70 * kmh2ms
    elif klasa == 'G': # główna
        return 60 * kmh2ms
    elif klasa == 'Z': # zbiorcza
        return 50 * kmh2ms
    elif klasa == 'L': # lokalna
        return 40 * kmh2ms
    elif klasa == 'D': # dojazdowa
        return 20 * kmh2ms
    elif klasa == 'I': # inna
        return 20 * kmh2ms
    else:
        return 10 * kmh2ms

def execute_query(query, parameters=None):
    with driver.session(database=database_name) as session:
        session.run(query, parameters)

# Zaokrąglanie współrzędnych do 1 metra
def round_coordinates(coord):
    return round(coord, 0)  # 0 miejsc po przecinku → pełne metry

# Dodawanie węzłów z zaokrąglonymi współrzędnymi
for node in nodes:
    rounded_x = round_coordinates(node[0])
    rounded_y = round_coordinates(node[1])
    
    # Konwersja do WGS84
    lon, lat = convert_to_wgs84(rounded_x, rounded_y)

    execute_query("""
    MERGE (n:Node {id: $id})
    SET n.y = $y, n.x = $x, n.longitude = $lon, n.latitude = $lat
    """, parameters={
        "id": f"{rounded_x}_{rounded_y}",
        "y": rounded_y,
        "x": rounded_x,
        "lon": lon,
        "lat": lat
    })

# Dodawanie relacji z zaokrąglonymi współrzędnymi
for _, row in edges.iterrows():
    start_x, start_y = row['start_point']
    end_x, end_y = row['end_point']

    # Zaokrąglamy współrzędne przed użyciem jako ID
    start_x, start_y = round_coordinates(start_x), round_coordinates(start_y)
    end_x, end_y = round_coordinates(end_x), round_coordinates(end_y)

    edge_params = {
        "start_id": f"{start_x}_{start_y}",
        "end_id": f"{end_x}_{end_y}",
        "class": row['klasaDrogi'],
        "direction": row['kierunek'],
        "speed": round(speed(row['klasaDrogi']), 3),
        "length": round(row['Shape_Leng'], 3),
        "time_seconds": round(row['Shape_Leng'] / speed(row['klasaDrogi']), 3)
    }

    execute_query("""
    MATCH (start:Node {id: $start_id}), (end:Node {id: $end_id})
    MERGE (start)-[:ROAD {class: $class, direction: $direction, speed: $speed, length: $length, time_seconds: $time_seconds}]->(end)
    """, parameters=edge_params)

    # Dodanie drugiej krawędzi w przeciwnym kierunku
    execute_query("""
    MATCH (start:Node {id: $end_id}), (end:Node {id: $start_id})
    MERGE (start)-[:ROAD {class: $class, direction: $direction, speed: $speed, length: $length, time_seconds: $time_seconds}]->(end)
    """, parameters=edge_params)
