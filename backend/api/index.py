import os
import sys
import pandas as pd
import numpy as np
import igraph as ig
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

# Initialize FastAPI App
app = FastAPI(
    title="Tax Network Analysis API",
    description="Backend Serverless untuk Klasterisasi Hubungan Kepemilikan Saham Wajib Pajak",
    version="1.0.2"
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
            # BERSIHKAN DATA SAAT DIBACA: Isi NaN dengan nilai aman agar tidak membuat server crash
            df_nodes = pd.read_csv(p_node).fillna({"nama": "Unknown", "jenis_node": "Badan"})
            df_edges = pd.read_csv(p_edge)
            df_edges['nilai'] = df_edges['nilai'].fillna(0.0)
            df_edges['dividen'] = df_edges['dividen'].fillna(0.0)
            df_edges['persentase'] = df_edges['persentase'].fillna(0.0)
            df_edges['jenis_relasi'] = df_edges['jenis_relasi'].fillna("KEPEMILIKAN_SAHAM")
            break
    except Exception:
        continue

# Failsafe Generator: Jika CSV tidak terbaca sama sekali oleh server
if df_nodes is None or df_edges is None:
    df_nodes = pd.DataFrame([{"id": 39868583, "nama": "WARN: CSV Terbaca Kosong di Vercel", "jenis_node": "Badan"}])
    df_edges = pd.DataFrame([{"rel_id": 1, "sumber": 39868583, "target": 39868583, "persentase": 100.0, "nilai": 0.0, "dividen": 0.0, "jenis_relasi": "ERROR"}])

# Ensure string types for joining safely later
df_nodes['id'] = df_nodes['id'].astype(str)
df_edges['sumber'] = df_edges['sumber'].astype(str)
df_edges['target'] = df_edges['target'].astype(str)

# ==============================================================================
# AUTHENTICATION SECURITY LAYER
# ==============================================================================
def verify_password(x_app_password: str = Header(None)):
    secure_password = os.environ.get("APP_PASSWORD", "default_fallback_password")
    if x_app_password != secure_password:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid App Password")
    return True

# ==============================================================================
# MAIN CORE NETWORK ROUTE (PERBAIKAN TOTAL DATA SANITIZATION)
# ==============================================================================
@app.get("/api/network", dependencies=[Depends(verify_password)])
def get_network(target_id: str = None, min_percentage: float = 0.0, node_type: str = "Semua"):
    
    # 1. Filter relasi berdasarkan minimal kepemilikan saham (%)
    filtered_edges = df_edges[df_edges['persentase'] >= min_percentage].copy()
    
    # Ambil daftar entitas unik dari relasi terfilter
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

    # Jika setelah difilter tidak menyisakan data apa pun
    if len(filtered_edges) == 0:
        return []

    # 3. Bangun Struktur Graf Jaringan menggunakan python-igraph
    g = ig.Graph.TupleList(
        filtered_edges[['sumber', 'target', 'persentase', 'nilai', 'dividen', 'jenis_relasi']].itertuples(index=False),
        directed=True,
        edge_attrs=['persentase', 'nilai', 'dividen', 'jenis_relasi']
    )
    
    # 4. Deteksi Komunitas Terafiliasi menggunakan Metode Louvain (Multilevel)
    g_undirected = g.as_undirected()
    communities = g_undirected.community_multilevel()
    
    community_map = {}
    for cluster_idx, cluster in enumerate(communities):
        for vertex_idx in cluster:
            node_name_id = str(g.vs[vertex_idx]['name'])
            community_map[node_name_id] = f"Group_{cluster_idx + 1}"

    # 5. Logika Pengaman Pencarian Fokus Ekosistem Target 2-Hop
    nodes_to_include = set(g.vs['name'])
    
    if target_id:
        target_str = str(target_id).strip()
        # Jika target ditemukan dalam graf terfilter, cari tetangga tingkat 1 dan 2
        if target_str in g.vs['name']:
            v_obj = g.vs.find(name=target_str)
            # Dapatkan semua node tetangga (anak-perusahaan / induk) langsung via objek graf
            neighbors_indices = g.neighborhood(vertices=v_obj.index, order=2, mode="all")
            nodes_to_include = set([g.vs[idx]['name'] for idx in neighbors_indices])
        else:
            # Jika target_id tidak ada dalam ekosistem terfilter saat ini, return kosong dengan aman
            return []

    # 6. Susun Struktur JSON yang Kompatibel dengan Cytoscape.js Frontend
    cytoscape_elements = []
    added_groups = set()
    
    # Tambahkan Simpul/Lingkaran (Nodes)
    for v in g.vs:
        node_name_str = str(v['name'])
        if node_name_str not in nodes_to_include:
            continue
            
        node_info = df_nodes_filtered[df_nodes_filtered['id'] == node_name_str]
        
        nama_wp = node_info['nama'].values[0] if not node_info.empty else f"WP ID: {node_name_str}"
        jenis_wp = node_info['jenis_node'].values[0] if not node_info.empty else "Badan"
        group_id = community_map.get(node_name_str, "Tanpa_Grup")
        
        # Buat Kotak Induk Pengelompokan Louvain (Parent Compound Node)
        if group_id not in added_groups:
            cytoscape_elements.append({
                "data": {
                    "id": group_id, 
                    "label": f"Grup Afiliasi: {group_id}", 
                    "is_parent": True
                }
            })
            added_groups.add(group_id)

        # Buat Lingkaran Anggota WP
        cytoscape_elements.append({
            "data": {
                "id": node_name_str,
                "label": nama_wp,
                "parent": group_id,
                "jenis_node": jenis_wp,
                "is_parent": False
            }
        })

    # Tambahkan Garis Hubungan Kepemilikan (Edges) dengan proteksi Nilai Inf / NaN
    for e in g.es:
        source_node_str = str(g.vs[e.source]['name'])
        target_node_str = str(g.vs[e.target]['name'])
        
        if source_node_str in nodes_to_include and target_node_str in nodes_to_include:
            # Proteksi konversi angka agar selalu menghasilkan float valid/terbatas bagi JSON
            val_saham = float(e['nilai']) if (pd.notna(e['nilai']) and np.isfinite(e['nilai'])) else 0.0
            val_dividen = float(e['dividen']) if (pd.notna(e['dividen']) and np.isfinite(e['dividen'])) else 0.0
            val_persen = float(e['persentase']) if (pd.notna(e['persentase']) and np.isfinite(e['persentase'])) else 0.0

            cytoscape_elements.append({
                "data": {
                    "id": f"e_{source_node_str}_{target_node_str}",
                    "source": source_node_str,
                    "target": target_node_str,
                    "label": f"{val_persen}%",
                    "nilai": val_saham,
                    "dividen": val_dividen,
                    "jenis_relasi": str(e['jenis_relasi'])
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
