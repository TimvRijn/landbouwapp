// static/js/rvo-brp.js
(function (w) {
  'use strict';

  function ensureApiUrl() {
    if (!w.API_RVO_BRP) {
      throw new Error("API_RVO_BRP is niet gedefinieerd. Zet window.API_RVO_BRP = url_for('rvo_api.brp').");
    }
  }

  // Wacht totdat de Google Map bounds heeft
  function waitForBounds(map) {
    return new Promise((resolve) => {
      if (map && map.getBounds()) return resolve();
      // idle vuurt zodra de kaart voor het eerst gerenderd is
      google.maps.event.addListenerOnce(map, 'idle', () => resolve());
    });
  }

  // Maak RVO overlays leeg
  function clearRvoOverlays() {
    if (!w.rvoOverlays) w.rvoOverlays = [];
    w.rvoOverlays.forEach((o) => o.setMap && o.setMap(null));
    w.rvoOverlays = [];
    if (w.rvoInfoWindow) { w.rvoInfoWindow.close(); w.rvoInfoWindow = null; }
  }

  // Hulpje om nette fixed getallen te tonen
  function toFixed(num, digits = 4) {
    const n = Number(num);
    return Number.isFinite(n) ? n.toFixed(digits) : '';
  }

  async function loadRvoParcels(type) {
    try {
      ensureApiUrl();

      const map = (type === 'add') ? w.addMap : w.editMap;
      if (!map) {
        alert('Kaart is nog niet klaar.');
        return;
      }

      await waitForBounds(map);
      const bbox = w.mapBBOX(map);

      clearRvoOverlays();

      // Één call: altijd via je eigen proxy (same-origin -> geen CORS)
      const url = `${w.API_RVO_BRP}?bbox=${encodeURIComponent(bbox)}`;
      const res = await fetch(url, { headers: { 'Accept': 'application/json' } });

      if (!res.ok) {
        let msg = '';
        try { const j = await res.json(); msg = j.error || ''; } catch {}
        alert(`RVO (BRP) percelen konden niet geladen worden${msg ? `: ${msg}` : ` (HTTP ${res.status})`}.`);
        return;
      }

      let geojson;
      try { geojson = await res.json(); }
      catch { alert('Proxy gaf geen geldige JSON terug.'); return; }

      const features = Array.isArray(geojson.features) ? geojson.features : [];
      if (!features.length) {
        alert('Geen RVO (BRP) percelen in dit kaartbeeld. Zoom of verschuif de kaart en probeer opnieuw.');
        return;
      }

      const mapInstance = map;
      const infow = w.rvoInfoWindow || new google.maps.InfoWindow();
      w.rvoInfoWindow = infow;

      const makePolygon = (paths, props) => {
        const poly = new google.maps.Polygon({
          paths,
          fillColor: '#22c55e', fillOpacity: 0.22,
          strokeColor: '#16a34a', strokeOpacity: 0.9, strokeWeight: 2,
          map: mapInstance, clickable: true
        });

        poly.addListener('mouseover', () => poly.setOptions({ fillOpacity: 0.33 }));
        poly.addListener('mouseout', () => poly.setOptions({ fillOpacity: 0.22 }));

        poly.addListener('click', (ev) => {
          const outer = paths[0], holes = paths.slice(1);
          const aOuter = google.maps.geometry.spherical.computeArea(outer);
          const aHoles = holes.reduce((s, h) => s + google.maps.geometry.spherical.computeArea(h), 0);
          const ha = (aOuter - aHoles) / 10000;

          const gewas = props?.gewascode || props?.gewas || '-';
          const jaar  = props?.teeltjaar || props?.jaar || '-';

          infow.setContent(`
            <div style="font-family:Inter,system-ui,sans-serif">
              <div style="font-weight:700;margin-bottom:4px">RVO/BRP perceel</div>
              <div style="font-size:.85rem;color:#64748b;margin-bottom:8px">Gewas: <b>${gewas}</b> — Jaar: <b>${jaar}</b></div>
              <div style="font-size:.9rem;margin-bottom:6px">Oppervlakte: <b>${toFixed(ha)}</b> ha</div>
              <button id="adoptRvoBtn" style="padding:8px 12px;border:0;border-radius:8px;background:#22c55e;color:white;cursor:pointer;font-weight:600">Perceel overnemen</button>
            </div>
          `);
          infow.setPosition(ev.latLng);
          infow.open(mapInstance);

          google.maps.event.addListenerOnce(infow, 'domready', () => {
            const btn = document.getElementById('adoptRvoBtn');
            if (!btn) return;
            btn.addEventListener('click', () => {
              const prefix = (type === 'add') ? 'add' : 'edit';

              // oppervlakte + hidden fields
              document.getElementById(prefix + 'CalculatedArea').textContent = toFixed(ha) + ' hectare';
              document.getElementById(prefix + 'CalculatedAreaValue').value   = toFixed(ha);
              document.querySelector(`#${type === 'add' ? 'addForm' : 'editForm'} input[name="oppervlakte"]`).value = toFixed(ha);

              const coords = outer.map(p => ({ lat: p.lat(), lng: p.lng() }));
              document.getElementById(prefix + 'PolygonCoords').value = JSON.stringify(coords);

              const b = new google.maps.LatLngBounds();
              outer.forEach(ll => b.extend(ll));
              const c = b.getCenter();
              document.getElementById(prefix + 'Latitude').value = c.lat().toString();
              document.getElementById(prefix + 'Longitude').value = c.lng().toString();
              const lbl = document.getElementById(prefix + 'SelectedCoords');
              if (lbl) lbl.textContent = `${c.lat().toFixed(6)}, ${c.lng().toFixed(6)}`;
              w.geocoder.geocode({ location: c }, (results, status) => {
                const out = (status === 'OK' && results && results[0]) ? results[0].formatted_address : '—';
                const adresField = document.getElementById(prefix + 'Adres');
                if (adresField) adresField.value = out;
                const lab = document.getElementById(prefix + 'SelectedAddress');
                if (lab) lab.textContent = out;
              });

              // zet editable polygon in de map en koppel listeners
              if (type === 'edit') {
                if (w.editPolygon) w.editPolygon.setMap(null);
                w.editPolygon = new google.maps.Polygon({
                  paths: outer, editable: true, draggable: false,
                  strokeColor:'#16a34a', strokeOpacity:0.9, strokeWeight:2,
                  fillColor:'#22c55e', fillOpacity:0.28, map: mapInstance
                });
                ['set_at', 'insert_at', 'remove_at'].forEach(evt => {
                  w.editPolygon.getPath().addListener(evt, () => {
                    const A = google.maps.geometry.spherical.computeArea(w.editPolygon.getPath()) / 10000;
                    document.getElementById('editCalculatedArea').textContent = toFixed(A) + ' hectare';
                    document.getElementById('editCalculatedAreaValue').value = toFixed(A);
                    const coords = w.editPolygon.getPath().getArray().map(ll => ({ lat: ll.lat(), lng: ll.lng() }));
                    document.getElementById('editPolygonCoords').value = JSON.stringify(coords);
                  });
                });
                if (w.editDrawingManager) w.editDrawingManager.setDrawingMode(null);
                document.getElementById('editPolygonTool')?.classList.remove('active');
              } else {
                if (w.addPolygon) w.addPolygon.setMap(null);
                w.addPolygon = new google.maps.Polygon({
                  paths: outer, editable: true, draggable: false,
                  strokeColor:'#16a34a', strokeOpacity:0.9, strokeWeight:2,
                  fillColor:'#22c55e', fillOpacity:0.28, map: mapInstance
                });
                ['set_at', 'insert_at', 'remove_at'].forEach(evt => {
                  w.addPolygon.getPath().addListener(evt, () => {
                    const A = google.maps.geometry.spherical.computeArea(w.addPolygon.getPath()) / 10000;
                    document.getElementById('addCalculatedArea').textContent = toFixed(A) + ' hectare';
                    document.getElementById('addCalculatedAreaValue').value = toFixed(A);
                    const coords = w.addPolygon.getPath().getArray().map(ll => ({ lat: ll.lat(), lng: ll.lng() }));
                    document.getElementById('addPolygonCoords').value = JSON.stringify(coords);
                  });
                });
                if (w.addDrawingManager) w.addDrawingManager.setDrawingMode(null);
                document.getElementById('addPolygonTool')?.classList.remove('active');
              }

              infow.close();
            });
          });
        });

        if (!w.rvoOverlays) w.rvoOverlays = [];
        w.rvoOverlays.push(poly);
      };

      // GeoJSON -> Google Maps polygonen
      features.forEach((f) => {
        const g = f.geometry;
        const props = f.properties || {};
        if (!g) return;

        if (g.type === 'Polygon') {
          // coordinates = [outer,[hole1]...], elke ring als [lng,lat]
          const rings = g.coordinates.map(r => r.map(([lng, lat]) => new google.maps.LatLng(+lat, +lng)));
          makePolygon(rings, props);
        } else if (g.type === 'MultiPolygon') {
          g.coordinates.forEach(poly => {
            const rings = poly.map(r => r.map(([lng, lat]) => new google.maps.LatLng(+lat, +lng)));
            makePolygon(rings, props);
          });
        }
      });

    } catch (err) {
      console.error(err);
      alert('RVO (BRP) percelen konden niet geladen worden. Controleer de proxy (/api/rvo/brp) en probeer opnieuw.');
    }
  }

  // Exporteer publiek
  w.waitForBounds = waitForBounds;
  w.clearRvoOverlays = clearRvoOverlays;
  w.loadRvoParcels = loadRvoParcels;

})(window);
