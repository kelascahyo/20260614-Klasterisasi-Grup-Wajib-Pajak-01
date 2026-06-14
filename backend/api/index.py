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
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Menggunakan letak absolut berbasis direktori file ini agar serverless tidak tersesat mencari CSV
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
nodes_path = os.path.join(BASE_DIR, "data", "nodes_masked.csv")
edges_path = os.path.join(BASE_DIR, "data", "edges_masked.csv")

try:
    df_nodes = pd.read_csv(nodes_path)
    df_edges = pd.read_csv(edges_path)
except Exception as e:
    # Fallback alternatif jika folder data dipindah ke root project
    ROOT_DIR = os.path.dirname(BASE_DIR)
    df_nodes = pd.read_csv(os.path.join(ROOT_DIR, "data", "nodes_masked.csv"))
    df_edges = pd.read_csv(os.path.join(ROOT_DIR, "data", "edges_masked.csv"))

def verify_password(x_app_password: str = Header(None)):
    secure_password = os.environ.get("APP_PASSWORD", "default_fallback_password")
    if x_app_password != secure_password:
        raise HTTPException(status_code=401, detail="Unauthorized: Invalid Password")
    return True

@app.get("/api/network", dependencies=[Depends(verify_password)])
def get_network(target_id: int = None, min_percentage: float = 0.0, node_type: str = "Semua"):
    filtered_edges = df_edges[df_edges['persentase'] >= min_percentage].copy()
    
    unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
    df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()
    
    if node_type != "Semua":
        allowed_nodes = df_nodes_filtered[df_nodes_filtered['jenis_node'] == node_type]['id'].tolist()
        filtered_edges = filtered_edges[filtered_edges['sumber'].isin(allowed_nodes) & filtered_edges['target'].isin(allowed_nodes)]
        unique_nodes = pd.concat([filtered_edges['sumber'], filtered_edges['target']]).unique()
        df_nodes_filtered = df_nodes[df_nodes['id'].isin(unique_nodes)].copy()

    if len(filtered_edges) == 0:
        return []

    g = ig.Graph.TupleList(
        filtered_edges[['sumber', 'target', 'persentase', 'nilai', 'dividen', 'jenis_relasi']].itertuples(index=False),
        directed=True,
        edge_attrs=['persentase', 'nilai', 'dividen', 'jenis_relasi']
    )
    
    g_undirected = g.as_undirected()
    communities = g_undirected.community_multilevel()
    
    community_map = {}
    for cluster_idx, cluster in enumerate(communities):
        for vertex_idx in cluster:
            node_name_id = g.vs[vertex_idx]['name']
            community_map[node_name_id] = f"Group_{cluster_idx + 1}"

    nodes_to_include = set(g.vs['name'])
    if target_id and target_id in g.vs['name']:
        v_idx = g.vs.find(name=target_id).index
        neighbors = g.neighborhood(vertices=v_idx, order=2, mode="all")
        nodes_to_include = set([g.vs[n]['name'] for n in neighbors])

    cytoscape_elements = []
    added_groups = set()
    
    for v in g.vs:
        if v['name'] not in nodes_to_include:
            continue
            
        node_id = int(v['name'])
        node_info = df_nodes_filtered[df_nodes_filtered['id'] == node_id]
        
        nama_wp = node_info['nama'].values[0] if not node_info.empty else f"Unknown ({node_id})"
        jenis_wp = node_info['jenis_node'].values[0] if not node_info.empty else "Badan"
        group_id = community_map.get(node_id, "Tanpa_Grup")
        
        if group_id not in added_groups:
            cytoscape_elements.append({
                "data": {"id": group_id, "label": f"Konglomerasi: {group_id}", "is_parent": True}
            })
            added_groups.add(group_id)

        cytoscape_elements.append({
            "data": {
                "id": str(node_id),
                "label": nama_wp,
                "parent": group_id,
                "jenis_node": jenis_wp,
                "is_parent": False
            }
        })

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

handler = Mangum(app)
