import os
import sys
import pandas as pd
import igraph as ig
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

# Initialize FastAPI App
app = FastAPI(
    title="Tax Network Analysis API",
    description="Backend Serverless untuk Klasterisasi Hubungan Kepemilikan Saham Wajib Pajak",
    version="1.0.1"
)

# Enable CORS so your React Frontend can securely communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ==============================================================================
# SMART DATA ROUTING & AUTO-FALLBACK FOR CSV FILES
# ==============================================================================
CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.dirname(CURRENT_DIR)
ROOT_DIR = os.path.dirname(BACKEND_DIR)

paths_to_try_nodes = [
    os.path.join(BACKEND_DIR, "data", "nodes_masked.csv"),
    os.path.join(ROOT_DIR, "data", "nodes_masked.csv"),
    os.path.join(CURRENT_DIR, "nodes_masked.csv"),
    "data/nodes_masked.csv"
]

paths_to_try_edges = [
    os.path.join(BACKEND_DIR, "data", "edges_masked.csv"),
    os.path.join(ROOT_DIR, "data", "edges_masked.csv"),
    os.path.join(CURRENT_DIR, "edges_masked.csv"),
    "data/edges_masked.csv"
]

df_nodes = None
df_edges = None

for p_node, p_edge in zip(paths_to_try_nodes, paths_to_try_edges):
    try:
        if os.path.exists(p_node) and os.path.exists(p_edge):
            df_nodes = pd.read_csv(p_node)
            df_edges = pd.read_csv(p_edge)
            break
    except Exception:
        continue

# Failsafe Generator: If all paths fail, create a descriptive emergency data node 
if df_nodes is None or df_edges is None:
    df_nodes = pd.DataFrame([{
        "id": 39868583, 
        "nama": "SISTEM WARN: File CSV Tidak Ditemukan di Server Backend", 
        "jenis_node": "Badan"
    }])
    df_edges = pd.DataFrame([{
        "rel_id": 1, 
        "sumber": 39868583, 
        "target": 39868583, 
        "persentase": 100.0, 
        "nilai": 0, 
        "dividen": 0, 
        "jenis_relasi": "ERROR"
    }])

# ==============================================================================
# AUTHENTICATION SECURITY LAYER
# ==============================================================================
def verify_password(x_app_password: str = Header(None)):
    secure_password = os.environ.get("APP_PASSWORD", "default_fallback_password")
    if x_app_password != secure_password:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid App Password")
    return True

# ==============================================================================
# MAIN CORE NETWORK ROUTE (PERBAIKAN TYPE DATA STR/INT)
# ==============================================================================
@app.get("/api/network", dependencies=[Depends(verify_password)])
def get_network(target_id: str = None, min_percentage: float = 0.0, node_type: str = "Semua"):
    """
    Endpoint Utama: Memfilter relasi, mendeteksi komunitas/grup dengan Louvain,
    dan memetakan ekosistem (2-hop jika target_id diisi).
    """
    # 1. Filter structural edges berdasarkan batas kepemilikan saham (%)
    filtered_edges = df_edges[df_edges['persentase'] >= min_percentage].copy()
    
    # Ambil daftar unik entitas yang tersisa dari relasi tersebut
    unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
    df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()
    
    # 2. Filter berdasarkan tipe Wajib Pajak (Badan / Orang Pribadi / LN)
    if node_type != "Semua":
        allowed_nodes = df_nodes_filtered[df_nodes_filtered['jenis_node'] == node_type]['id'].tolist()
        filtered_edges = filtered_edges[
            filtered_edges['sumber'].isin(allowed_nodes) & 
            filtered_edges['target'].isin(allowed_nodes)
        ]
        unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
        df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()

    # Cek jika tidak ada data yang memenuhi kriteria filter
    if len(filtered_edges) == 0:
        return []

    # 3. Bangun Struktur Graf Jaringan menggunakan python-igraph
    # Catatan: Fungsi ini mengubah ID sumber & target menjadi String di dalam graf (g.vs['name'])
    g = ig.Graph.TupleList(
        filtered_edges[['sumber', 'target', 'persentase', 'nilai', 'dividen', 'jenis_relasi']].itertuples(index=False),
        directed=True,
        edge_attrs=['persentase', 'nilai', 'dividen', 'jenis_relasi']
    )
    
    # 4. Deteksi Komunitas Terafiliasi menggunakan Metode Louvain (Multilevel)
    g_undirected = g.as_undirected()
    communities = g_undirected.community_multilevel()
    
    # Petakan setiap entitas ke dalam ID Kelompok Ekosistem mereka masing-masing
    community_map = {}
    for cluster_idx, cluster in enumerate(communities):
        for vertex_idx in cluster:
            node_name_id = str(g.vs[vertex_idx]['name'])
            community_map[node_name_id] = f"Group_{cluster_idx + 1}"

    # 5. Fokus Analisis Berbasis Target Pajak (Fokus 2-Hop Network)
    nodes_to_include = set(g.vs['name'])
    
    if target_id:
        target_str = str(target_id).strip()
        if target_str in g.vs['name']:
            v_idx = g.vs.find(name=target_str).index
            # neighborhood order 2 mencakup anak-perusahaan dan induk (2 level relasi dari target)
            neighbors = g.neighborhood(vertices=v_idx, order=2, mode="all")
            nodes_to_include = set([g.vs[n]['name'] for n in neighbors])
        else:
            # Jika target_id diisi tetapi tidak ditemukan di dalam relasi graf terfilter
            return []

    # 6. Susun Struktur Output Data ke Format Cytoscape.js JSON
    cytoscape_elements = []
    added_groups = set()
    
    # Tambahkan Simpul/Lingkaran (Nodes)
    for v in g.vs:
        node_name_str = str(v['name'])
        if node_name_str not in nodes_to_include:
            continue
            
        try:
            node_id_int = int(node_name_str)
        except ValueError:
            node_id_int = node_name_str
            
        node_info = df_nodes_filtered[df_nodes_filtered['id'] == node_id_int]
        
        nama_wp = node_info['nama'].values[0] if not node_info.empty else f"WP ID {node_name_str}"
        jenis_wp = node_info['jenis_node'].values[0] if not node_info.empty else "Badan"
        group_id = community_map.get(node_name_str, "Tanpa_Grup")
        
        # Buat Kotak Induk (Parent Compound Node) untuk mengelompokkan grup konglomerasi
        if group_id not in added_groups:
            cytoscape_elements.append({
                "data": {
                    "id": group_id, 
                    "label": f"Grup Afiliasi: {group_id}", 
                    "is_parent": True
                }
            })
            added_groups.add(group_id)

        # Buat Lingkaran Anggota Perusahaan/Orang Pribadi
        cytoscape_elements.append({
            "data": {
                "id": node_name_str,
                "label": nama_wp,
                "parent": group_id,
                "jenis_node": jenis_wp,
                "is_parent": False
            }
        })

    # Tambahkan Garis Hubungan/Kepemilikan (Edges)
    for e in g.es:
        source_node_str = str(g.vs[e.source]['name'])
        target_node_str = str(g.vs[e.target]['name'])
        
        if source_node_str in nodes_to_include and target_node_str in nodes_to_include:
            cytoscape_elements.append({
                "data": {
                    "id": f"e_{source_node_str}_{target_node_str}",
                    "source": source_node_str,
                    "target": target_node_str,
                    "label": f"{e['persentase']}%",
                    "nilai": float(e['nilai']) if e['nilai'] else 0.0,
                    "dividen": float(e['dividen']) if e['dividen'] else 0.0,
                    "jenis_relasi": e['jenis_relasi']
                }
            })

    return cytoscape_elements

# Health check route
@app.get("/api/health")
def health_check():
    return {"status": "healthy", "nodes_loaded": len(df_nodes) if df_nodes is not None else 0}

# ==============================================================================
# VERCEL SERVERLESS HANDLER WRAPPER
# ==============================================================================
handler = Mangum(app)
