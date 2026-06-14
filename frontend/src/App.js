import React, { useState, useEffect, useRef } from 'react';
import cytoscape from 'cytoscape';
import contextMenus from 'cytoscape-context-menus';
import 'cytoscape-context-menus/cytoscape-context-menus.css';
import './App.css';

// Daftarkan plugin context menu ke cytoscape
if (typeof cytoscape.use === 'function' && !cytoscape.prototype.contextMenus) {
  cytoscape.use(contextMenus);
}

function App() {
  const containerRef = useRef(null);
  const cyRef = useRef(null);
  
  // State Input Parameter
  const [apiUrl, setApiUrl] = useState('');
  const [password, setPassword] = useState('');
  const [searchId, setSearchId] = useState('');
  const [minPercentage, setMinPercentage] = useState(0);
  const [nodeType, setNodeType] = useState('Semua');
  
  // State untuk Detail Profil Kanan/Informasi Klik
  const [selectedProfile, setSelectedProfile] = useState(null);
  const [loading, setLoading] = useState(false);

  const fetchData = async () => {
    if (!apiUrl || !password) {
      alert('Please fill in the Backend API URL and Password first!');
      return;
    }
    setLoading(true);
    try {
      let url = `${apiUrl}/api/network?min_percentage=${minPercentage}&node_type=${nodeType}`;
      if (searchId) url += `&target_id=${searchId}`;

      const res = await fetch(url, {
        headers: { 'X-App-Password': password }
      });

      if (!res.ok) throw new Error('Unauthorized or Network Error');
      const data = await res.json();
      renderGraph(data);
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  };

  const renderGraph = (elements) => {
    if (!containerRef.current) return;

    cyRef.current = cytoscape({
      container: containerRef.current,
      elements: elements,
      style: [
        {
          selector: 'node[?is_parent]',
          style: {
            'background-color': '#e2e8f0',
            'label': 'data(label)',
            'shape': 'rectangle',
            'text-valign': 'top',
            'text-halign': 'center',
            'font-size': '14px',
            'font-weight': 'bold',
            'padding': '20px'
          }
        },
        {
          selector: 'node[!is_parent]',
          style: {
            'background-color': function(ele) {
              const type = ele.data('jenis_node');
              if (type === 'Badan') return '#3b82f6'; // Biru
              if (type === 'LN') return '#ef4444';    // Merah (Luar Negeri)
              return '#10b981';                       // Hijau (Orang Pribadi)
            },
            'label': 'data(label)',
            'color': '#000',
            'font-size': '11px',
            'text-valign': 'center',
            'text-halign': 'center',
            'width': '60px',
            'height': '60px'
          }
        },
        {
          selector: 'edge',
          style: {
            'width': 2,
            'line-color': '#94a3b8',
            'target-arrow-color': '#94a3b8',
            'target-arrow-shape': 'triangle',
            'curve-style': 'bezier',
            'label': 'data(label)',
            'font-size': '10px',
            'text-rotation': 'autorotate'
          }
        }
      ],
      layout: {
        name: 'cose', // Layout otomatis bawaan cytoscape yang mendukung compound nodes
        animate: true,
        padding: 30
      }
    });

    // Inisialisasi Klik Kanan Context Menu
    cyRef.current.contextMenus({
      menuItems: [
        {
          id: 'view-profile',
          content: '🔎 View Corporate Profile',
          selector: 'node[!is_parent]',
          onClick: (event) => {
            const targetNode = event.target;
            setSelectedProfile({
              id: targetNode.data('id'),
              name: targetNode.data('label'),
              type: targetNode.data('jenis_node'),
              group: targetNode.data('parent')
            });
          }
        }
      ]
    });
  };

  return (
    <div className="app-container">
      <header>
        <h2>Taxpayer Conglomeration Network Explorer</h2>
      </header>
      
      <div className="main-layout">
        <aside className="sidebar">
          <h3>⚙️ Connection & Security</h3>
          <div className="form-group">
            <label>Backend API URL</label>
            <input type="text" placeholder="https://your-backend.vercel.app" value={apiUrl} onChange={e => setApiUrl(e.target.value)} />
          </div>
          <div className="form-group">
            <label>App Password</label>
            <input type="password" placeholder="Enter secure password" value={password} onChange={e => setPassword(e.target.value)} />
          </div>

          <hr/>
          <h3>🔍 Network Filters</h3>
          <div className="form-group">
            <label>Search Taxpayer ID</label>
            <input type="text" placeholder="e.g., 39868583" value={searchId} onChange={e => setSearchId(e.target.value)} />
          </div>
          <div className="form-group">
            <label>Min. Shareholding (%)</label>
            <input type="number" value={minPercentage} onChange={e => setMinPercentage(parseFloat(e.target.value) || 0)} />
          </div>
          <div className="form-group">
            <label>Taxpayer Type</label>
            <select value={nodeType} onChange={e => setNodeType(e.target.value)}>
              <option value="Semua">All Types</option>
              <option value="Badan">Badan (Corporate)</option>
              <option value="LN">LN (Foreign Entity)</option>
              <option value="Orang Pribadi">Orang Pribadi (Individual)</option>
            </select>
          </div>

          <button onClick={fetchData} disabled={loading}>
            {loading ? 'Analyzing Network...' : 'Analyze Ecosystem'}
          </button>

          {selectedProfile && (
            <div className="detail-box">
              <h4>📋 Taxpayer Profile (Selected)</h4>
              <p><strong>ID:</strong> {selectedProfile.id}</p>
              <p><strong>Name:</strong> {selectedProfile.name}</p>
              <p><strong>Type:</strong> {selectedProfile.type}</p>
              <p><strong>Affiliated Group:</strong> {selectedProfile.group}</p>
            </div>
          )}
        </aside>

        <main className="cy-container" ref={containerRef}>
          {(!cyRef.current) && <div style={{padding: '20px', color: '#64748b'}}>Configure parameters and click "Analyze Ecosystem" to view the network graph.</div>}
        </main>
      </div>
    </div>
  );
}

export default App;
