import os
import pandas as pd
import igraph as ig
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from mangum import Mangum

app = FastAPI(title="Tax Network Analysis API")

# Mengizinkan Frontend React mengakses Backend (CORS)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Ganti dengan domain Vercel frontend Anda jika sudah live
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Simulasi database di memory (Serverless akan meload ini saat cold start)
# Menggunakan data CSV yang diunggah user
try:
    df_nodes = pd.read_csv("data/nodes_masked.csv")
    df_edges = pd.read_csv("data/edges_masked.csv")
except Exception:
    # Fallback jika posisi path berbeda di Vercel
    df_nodes = pd.read_csv("../data/nodes_masked.csv")
    df_edges = pd.read_csv("../data/edges_masked.csv")

# Autentikasi Sederhana & Aman via Environment Variable
def verify_password(x_app_password: str = Header(None)):
    secure_password = os.environ.get("APP_PASSWORD", "default_fallback_password")
    if x_app_password != secure_password:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Password")
    return True

@app.get("/")
def read_root():
    return {"status": "Tax Network API is running"}

@app.get("/api/network", dependencies=[Depends(verify_password)])
def get_network(target_id: int = None, min_percentage: float = 0.0, node_type: str = "Semua"):
    # 1. Filter Edges berdasarkan persentase kepemilikan saham
    filtered_edges = df_edges[df_edges['persentase'] >= min_percentage]
    
    # 2. Bangun Graf Menggunakan python-igraph
    # Buat mapping ID unik untuk igraph
    unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
    df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()
    
    # Filter berdasarkan jenis WP jika dipilih selain "Semua"
    if node_type != "Semua":
        # Ambil node yang tipenya sesuai
        allowed_nodes = df_nodes_filtered[df_nodes_filtered['jenis_node'] == node_type]['id'].tolist()
        filtered_edges = filtered_edges[filtered_edges['sumber'].isin(allowed_nodes) & filtered_edges['target'].isin(allowed_nodes)]
        unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
        df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()

    if len(filtered_edges) == 0:
        return {"nodes": [], "edges": []}

    # Buat objek graf igraph
    g = ig.Graph.TupleList(
        filtered_edges[['sumber', 'target', 'persentase', 'nilai', 'dividen', 'jenis_relasi']].itertuples(index=False),
        directed=True,
        edge_attrs=['persentase', 'nilai', 'dividen', 'jenis_relasi']
    )
    
    # 3. Community Detection (Louvain / Walktrap untuk mengelompokkan grup konglomerasi)
    # Karena Louvain mendeteksi graf tidak berarah (undirected), kita ubah sementara untuk deteksi komunitas
    g_undirected = g.as_undirected()
    communities = g_undirected.community_multilevel() # Algoritma Louvain
    
    # Petakan hasil komunitas ke node
    community_map = {}
    for cluster_idx, cluster in enumerate(communities):
        for vertex_idx in cluster:
            node_name_id = g.vs[vertex_idx]['name']
            community_map[node_name_id] = f"Group_{cluster_idx + 1}"

    # 4. Filter Ego Network jika user mencari ID Spesifik
    nodes_to_include = set(g.vs['name'])
    if target_id and target_id in g.vs['name']:
        v_idx = g.vs.find(name=target_id).index
        # Ambil tetangga terdekat (1-hop / 2-hop)
        neighbors = g.neighborhood(vertices=v_idx, order=2, mode="all")
        nodes_to_include = set([g.vs[n]['name'] for n in neighbors])

    # 5. Format output JSON untuk Cytoscape.js (Mendukung Compound Nodes)
    cytoscape_elements = []
    
    # Tambahkan Compound Nodes (Kotak Pembungkus Grup/Komunitas)
    added_groups = set()
    
    for v in g.vs:
        if v['name'] not in nodes_to_include:
            continue
            
        node_id = int(v['name'])
        node_info = df_nodes_filtered[df_nodes_filtered['id'] == node_id]
        
        nama_wp = node_info['nama'].values[0] if not node_info.empty else f"Unknown ({node_id})"
        jenis_wp = node_info['jenis_node'].values[0] if not node_info.empty else "Badan"
        group_id = community_map.get(node_id, "Tanpa_Grup")
        
        # Daftarkan group parent ke cytoscape jika belum ada
        if group_id not in added_groups:
            cytoscape_elements.append({
                "data": {"id": group_id, "label": f"Konglomerasi: {group_id}", "is_parent": True}
            })
            added_groups.add(group_id)

        # Tambahkan node individu di dalam parent group
        cytoscape_elements.append({
            "data": {
                "id": str(node_id),
                "label": nama_wp,
                "parent": group_id,
                "jenis_node": jenis_wp,
                "is_parent": False
            }
        })

    # Tambahkan Edges (Hubungan Saham)
    for e in g.es:
        source_node = g.vs[e.source]['name']
        target_node = g.vs[e.target]['name']
        
        if source_node in nodes_to_include and target_node in nodes_to_include:
            cytoscape_elements.append({
                "data": {
                    "id": f"e_{source_node}_{target_node}",
                    "source": str(source_node),
                    "target": str(target_node),
                    "label": f"{e['persentase']}%",
                    "nilai": e['nilai'],
                    "dividen": e['dividen'],
                    "jenis_relasi": e['jenis_relasi']
                }
            })

    return cytoscape_elements

# Handler untuk Vercel Serverless
handler = Mangum(app)
