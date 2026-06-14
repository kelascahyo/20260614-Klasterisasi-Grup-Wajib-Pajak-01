const fetchData = async () => {
    if (!apiUrl || !password) {
      alert('Please fill in the Backend API URL and Password first!');
      return;
    }
    setLoading(true);
    try {
      // Membersihkan tanda garing (/) di ujung URL input jika ada
      const cleanBaseUrl = apiUrl.replace(/\/$/, "");
      
      // Membaca routing API secara dinamis dan aman
      let url = `${cleanBaseUrl}/api/network?min_percentage=${minPercentage}&node_type=${nodeType}`;
      if (searchId) url += `&target_id=${searchId}`;

      const res = await fetch(url, {
        headers: { 'X-App-Password': password }
      });

      if (!res.ok) throw new Error('Unauthorized or Network Error. Check your Password / API URL.');
      const data = await res.json();
      
      if (!Array.isArray(data)) {
        throw new Error('Server did not return a valid JSON array. Check Backend config.');
      }
      
      renderGraph(data);
    } catch (err) {
      alert(err.message);
    } finally {
      setLoading(false);
    }
  };
