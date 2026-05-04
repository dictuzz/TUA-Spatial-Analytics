import streamlit as st
import pandas as pd
import requests
import math
import time
from io import BytesIO
import folium
from streamlit_folium import st_folium

# --- LIBRARY BARU UNTUK PRODUCTION GRADE ---
import asyncio
import aiohttp
import plotly.express as px
from st_aggrid import AgGrid, GridOptionsBuilder

# -------------------------------------------------------------
# 1. KONFIGURASI HALAMAN & CUSTOM CSS (STICKY LAYOUT)
# -------------------------------------------------------------
st.set_page_config(page_title="Spatial Analyzer", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1200px; }
    .notion-h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-color); margin-bottom: 0.2rem; letter-spacing: -0.02em; }
    .notion-sub { font-size: 0.95rem; color: var(--text-color); opacity: 0.6; margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-color); }
    
    .notion-callout { display: flex; flex-direction: column; padding: 20px; background-color: var(--secondary-background-color); border-radius: 4px; border: 1px solid var(--border-color); margin-bottom: 24px; border-left: 4px solid var(--text-color); }
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    
    /* STICKY MAP CSS: Mengunci kolom kedua (kanan) agar tidak ikut terscroll */
    [data-testid="column"]:nth-of-type(2) {
        position: sticky;
        top: 3rem;
        height: calc(100vh - 3rem);
        overflow-y: auto;
    }
    /* Sembunyikan scrollbar di kolom kanan agar lebih bersih */
    [data-testid="column"]:nth-of-type(2)::-webkit-scrollbar { display: none; }
    
    .extra-data-row { display: flex; justify-content: space-between; border-bottom: 1px dashed var(--border-color); padding: 6px 0; font-size: 0.85rem; }
    .extra-data-row:last-child { border-bottom: none; }
</style>
""", unsafe_allow_html=True)

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# -------------------------------------------------------------
# 2. FUNGSI LOGIKA (SYNC & ASYNC)
# -------------------------------------------------------------
@st.cache_data(show_spinner=False, ttl=86400)
def cari_alamat(lat, lon):
    url = f"https://nominatim.openstreetmap.org/reverse?format=json&lat={lat}&lon={lon}&zoom=18&addressdetails=1"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    try:
        res = requests.get(url, headers=headers, timeout=10)
        if res.status_code == 200:
            data = res.json()
            addr = data.get("address", {})
            return data.get("display_name", "Tidak ditemukan"), \
                   addr.get("village", addr.get("suburb", addr.get("neighbourhood", "Tidak diketahui"))), \
                   addr.get("town", addr.get("district", addr.get("city_district", "Tidak diketahui"))), \
                   addr.get("city", addr.get("county", addr.get("region", "Tidak diketahui")))
    except: pass
    return "Error Server Peta", "Tidak diketahui", "Tidak diketahui", "Tidak diketahui"

def hitung_jarak_udara(lat1, lon1, lat2, lon2):
    try: return math.sqrt((float(lat1) - float(lat2))**2 + (float(lon1) - float(lon2))**2) * 111.12
    except: return 999999

def get_best_match(df_master, lat_val, lon_val, seg_name, col_seg, col_lat, col_lon, col_id, col_name):
    df_seg = df_master[df_master[col_seg].astype(str).str.strip().str.upper() == seg_name.upper()].copy()
    if not df_seg.empty:
        df_seg['tmp_dist'] = df_seg.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
        best = df_seg.loc[df_seg['tmp_dist'].idxmin()]
        
        kolom_inti = [col_seg, col_lat, col_lon, col_id, col_name, 'tmp_dist']
        extra_data = {col: best[col] for col in df_master.columns if col not in kolom_inti}
        
        return {
            "id": best[col_id], "nama": best[col_name], 
            "jarak_udara": round(best['tmp_dist'], 2),
            "lat": float(best[col_lat]), "lon": float(best[col_lon]),
            "extra_data": extra_data
        }
    return None

def analyze_catchment_area(df_master, lat_val, lon_val, radius_km, col_lat, col_lon, col_seg, col_id, col_name):
    df_temp = df_master.copy()
    df_temp['jarak_km'] = df_temp.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[col_lat], r[col_lon]), axis=1)
    df_in_radius = df_temp[df_temp['jarak_km'] <= radius_km]
    
    summary = {}
    for seg in df_in_radius[col_seg].unique():
        df_seg = df_in_radius[df_in_radius[col_seg] == seg].sort_values('jarak_km')
        daftar = []
        for _, row in df_seg.iterrows():
            kolom_inti = [col_seg, col_lat, col_lon, col_id, col_name, 'jarak_km']
            extra_data = {col: row[col] for col in df_master.columns if col not in kolom_inti}
            daftar.append({
                "id": row[col_id], "nama": row[col_name], "lat": float(row[col_lat]), "lon": float(row[col_lon]),
                "jarak_udara": round(row['jarak_km'], 2), "extra_data": extra_data
            })
        summary[seg] = {"jumlah": len(df_seg), "daftar": daftar}
    return summary, len(df_in_radius)

# --- FUNGSI ASYNC OSRM UNTUK BATCH PROCESSING SUPER CEPAT ---
async def fetch_osrm_async(session, lat1, lon1, lat2, lon2, s_name):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        async with session.get(url, timeout=5) as res:
            if res.status == 200:
                data = await res.json()
                if data.get("code") == "Ok" and len(data.get("routes", [])) > 0:
                    dist_km = round(data["routes"][0]["distance"] / 1000, 2)
                    time_min = round(data["routes"][0]["duration"] / 60, 1)
                    return s_name, dist_km, time_min
    except Exception as e: pass
    return s_name, "N/A", "N/A"

# -------------------------------------------------------------
# 3. SIDEBAR CONFIG
# -------------------------------------------------------------
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-bottom:8px;'>Database Master</div>", unsafe_allow_html=True)
template_path = "AHS_ACTIVE_FORMATTED.xlsx"
try:
    with open(template_path, "rb") as file:
        st.sidebar.download_button(label="Unduh Template Master AHS", data=file.read(), file_name="AHS_ACTIVE_FORMATTED.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
except: st.sidebar.error("File template 'AHS_ACTIVE_FORMATTED.xlsx' tidak ditemukan.")

uploaded_master = st.sidebar.file_uploader("Upload Excel File", type=["xlsx"], label_visibility="collapsed")

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Kolom Master</div>", unsafe_allow_html=True)
m_id = st.sidebar.text_input("Kolom ID", "ID_PELANGGAN").upper()
m_name = st.sidebar.text_input("Kolom Nama", "NAMA_PELANGGAN").upper()
m_seg = st.sidebar.text_input("Kolom Kategori / Segmen", "SEGMEN").upper()
m_lat = st.sidebar.text_input("Kolom Latitude", "LATITUDE").upper()
m_lon = st.sidebar.text_input("Kolom Longitude", "LONGITUDE").upper()

st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:24px; margin-bottom:8px;'>Mapping Quadran</div>", unsafe_allow_html=True)
q_kel = st.sidebar.text_input("Kolom Kelurahan", "KELURAHAN").upper()
q_kec = st.sidebar.text_input("Kolom Kecamatan", "KECAMATAN").upper()
q_kab = st.sidebar.text_input("Kolom Kabupaten", "KAB_KOT").upper()
q_res = st.sidebar.text_input("Kolom Quadran", "QUADRAN").upper()

# -------------------------------------------------------------
# 4. MAIN UI
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Spatial Analytics</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Tools untuk cek jarak dari satu titik ke titik lain.</div>", unsafe_allow_html=True)

tab_single, tab_batch = st.tabs(["Dashboard Catchment Area", "Async Batch Processing"])

list_segmen = []
if uploaded_master:
    try:
        df_master = pd.read_excel(uploaded_master, sheet_name=0)
        df_quad = pd.read_excel(uploaded_master, sheet_name=1)
        df_master.columns = df_master.columns.astype(str).str.strip().str.upper()
        df_quad.columns = df_quad.columns.astype(str).str.strip().str.upper()
        if m_seg in df_master.columns:
            list_segmen = df_master[m_seg].dropna().astype(str).str.strip().str.upper().unique().tolist()
        else: st.stop()
    except Exception as e: st.stop()

default_colors = ["#2D88FF", "#FF9900", "#00A86B", "#E03E3E", "#6B52D1", "#D9730D"]
segmen_colors = {seg: default_colors[i % len(default_colors)] for i, seg in enumerate(list_segmen)}

# ==========================================
# TAB 1: DASHBOARD CATCHMENT AREA (SPLIT LAYOUT)
# ==========================================
with tab_single:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>Parameter Ekspansi</div>", unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
        in_name = c1.text_input("Nama Target", "Target Baru")
        in_lat = c2.text_input("Latitude", "-6.914744")
        in_lon = c3.text_input("Longitude", "107.609810")
        radius_filter = c4.number_input("Radius (KM)", min_value=1, max_value=50, value=3)
        
        if st.button("Jalankan Analisis", type="primary"):
            with st.spinner("Membangun Dashboard..."):
                lat_v, lon_v = float(in_lat), float(in_lon)
                addr, kel, kec, kab = cari_alamat(lat_v, lon_v)
                
                quad = "Manual"
                if q_kel in df_quad.columns:
                    match = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False))]
                    if not match.empty: quad = str(match.iloc[0][q_res])

                matches = {s: get_best_match(df_master, lat_v, lon_v, s, m_seg, m_lat, m_lon, m_id, m_name) for s in list_segmen}
                catchment_summary, total_in_radius = analyze_catchment_area(df_master, lat_v, lon_v, radius_filter, m_lat, m_lon, m_seg, m_id, m_name)

                # Fetch OSRM darat secara Sync untuk tab Single ini
                for s, data in matches.items():
                    if data:
                        url = f"http://router.project-osrm.org/route/v1/driving/{lon_v},{lat_v};{data['lon']},{data['lat']}?overview=false"
                        try:
                            res_osrm = requests.get(url, timeout=5).json()
                            data['jarak_darat'] = round(res_osrm["routes"][0]["distance"]/1000, 2)
                            data['waktu_tempuh'] = round(res_osrm["routes"][0]["duration"]/60, 1)
                        except:
                            data['jarak_darat'], data['waktu_tempuh'] = "N/A", "N/A"

                st.session_state.analysis_result = {
                    "name": in_name, "lat": lat_v, "lon": lon_v, "addr": addr, "quad": quad, 
                    "matches": matches, "catchment": catchment_summary, "total_catchment": total_in_radius,
                    "radius_km": radius_filter, "admin": {"kel": kel, "kec": kec, "kab": kab}
                }

        if st.session_state.analysis_result:
            res = st.session_state.analysis_result
            st.write("---")
            
            # --- SPLIT LAYOUT (KIRI DAFTAR, KANAN PETA STICKY) ---
            col_list, col_map = st.columns([1.1, 1], gap="large")
            
            # [KOLOM KIRI]: Administrasi & Daftar Collapsible
            with col_list:
                st.markdown(f"""
                <div class="notion-callout" style="margin-bottom: 12px;">
                    <div class="callout-content">
                        <strong style="font-size: 1.1rem; display:block; margin-bottom:4px;">{res['name']}</strong>
                        <span style="font-size: 0.85rem; display:block; margin-bottom:8px; font-weight:600;">{res['admin']['kel']}, {res['admin']['kec']}, {res['admin']['kab']}</span>
                        <div><span class="tag tag-gray">Quadran Sistem</span><span class="tag" style="margin-left: 6px; background-color: rgba(45,136,255,0.1); color: #2D88FF; border: 1px solid rgba(45,136,255,0.2);">{res['quad']}</span></div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                st.markdown(f"<div class='card-prop-name' style='font-size: 1rem; margin-top: 24px;'>Detail {res['total_catchment']} Outlet (Radius {res['radius_km']} KM)</div>", unsafe_allow_html=True)
                if res['total_catchment'] == 0:
                    st.info("Area kosong. Tidak ada outlet terdekat.")
                else:
                    for seg in list_segmen:
                        if seg in res['catchment']:
                            data = res['catchment'][seg]
                            st.markdown(f"**🏷️ Segmen: {seg} ({data['jumlah']} Outlet)**")
                            for idx, item in enumerate(data['daftar']):
                                title = f"🥇 {item['nama']} (Terdekat - {item['jarak_udara']} KM)" if idx == 0 else f"📍 {item['nama']} ({item['jarak_udara']} KM)"
                                with st.expander(title, expanded=(idx==0)):
                                    sc1, sc2 = st.columns(2)
                                    with sc1:
                                        st.markdown(f"**ID:** `{item['id']}`")
                                        st.markdown(f"**Jarak Udara:** {item['jarak_udara']} KM")
                                        if idx == 0 and res['matches'][seg]:
                                            match_s = res['matches'][seg]
                                            st.markdown(f"<span style='color:#2D88FF;'>**Jarak Darat:** {match_s['jarak_darat']} KM</span>", unsafe_allow_html=True)
                                            st.markdown(f"<span style='color:#2D88FF;'>**Waktu Tempuh:** {match_s['waktu_tempuh']} Min</span>", unsafe_allow_html=True)
                                    with sc2:
                                        for k, v in item['extra_data'].items():
                                            val = v if pd.notna(v) and str(v).strip() != "" else "-"
                                            st.markdown(f"<div class='extra-data-row'><strong>{k}</strong><span>{val}</span></div>", unsafe_allow_html=True)
                            st.write("")

            # [KOLOM KANAN]: Peta & Chart (Sticky)
            with col_map:
                # 1. Plotly Donut Chart
                if res['total_catchment'] > 0:
                    labels = list(res['catchment'].keys())
                    values = [d['jumlah'] for d in res['catchment'].values()]
                    pie_colors = [segmen_colors.get(l, '#ccc') for l in labels]
                    
                    fig = px.pie(names=labels, values=values, hole=0.5, title=f"Proporsi Penguasaan Pasar")
                    fig.update_traces(marker=dict(colors=pie_colors), textinfo='percent+label', hoverinfo='label+percent+value')
                    fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=250, showlegend=False)
                    st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

                # 2. Folium Map Interaktif
                m = folium.Map(location=[res['lat'], res['lon']], zoom_start=13, tiles="cartodb positron")
                folium.Circle([res['lat'], res['lon']], radius=res['radius_km'] * 1000, color='#2D88FF', fill=True, fill_opacity=0.1, weight=1).add_to(m)
                folium.Marker([res['lat'], res['lon']], popup="<b>TARGET</b>", icon=folium.Icon(color="black", icon="star")).add_to(m)
                
                bounds = [[res['lat'], res['lon']]]
                for seg, data in res['catchment'].items():
                    col_hex = segmen_colors.get(seg, "gray")
                    for idx, item in enumerate(data['daftar']):
                        if idx == 0: folium.PolyLine([[res['lat'], res['lon']], [item['lat'], item['lon']]], color=col_hex, weight=2, dash_array='4,4').add_to(m)
                        popup_html = f"<div style='min-width:150px;'><b>[{seg}] {item['nama']}</b><br>Jarak: {item['jarak_udara']} KM</div>"
                        folium.Marker([item['lat'], item['lon']], popup=folium.Popup(popup_html, max_width=250), icon=folium.Icon(color="lightgray", icon="info-sign")).add_to(m)
                        bounds.append([item['lat'], item['lon']])
                
                if len(bounds) > 1: m.fit_bounds(bounds)
                st_folium(m, height=450, use_container_width=True, key="map_dashboard")

# ==========================================
# TAB 2: ASYNC BATCH PROCESSING & AG-GRID
# ==========================================
with tab_batch:
    if uploaded_master:
        st.markdown("<div class='card-prop-name'>Batch Engine Asynchronous</div>", unsafe_allow_html=True)
        uploaded_batch = st.file_uploader("Upload daftar lokasi target (.xlsx)", type=["xlsx"], key="batch_upload")
        
        if uploaded_batch:
            df_batch = pd.read_excel(uploaded_batch)
            df_batch.columns = df_batch.columns.astype(str).str.strip().str.upper()
            
            bc1, bc2, bc3, bc4 = st.columns(4)
            b_name = bc1.selectbox("Kolom Nama Target", df_batch.columns)
            b_lat = bc2.selectbox("Kolom Latitude", df_batch.columns, index=min(1, len(df_batch.columns)-1))
            b_lon = bc3.selectbox("Kolom Longitude", df_batch.columns, index=min(2, len(df_batch.columns)-1))
            batch_radius = bc4.number_input("Radius (KM)", min_value=1, max_value=50, value=3)

            if st.button("Mulai Pemrosesan Async", type="primary"):
                progress_bar = st.progress(0)
                status_text = st.empty()
                results = []
                total = len(df_batch)

                # Definisi Async Execution Loop
                async def run_batch_processing():
                    async with aiohttp.ClientSession() as session:
                        for index, row in df_batch.iterrows():
                            progress_bar.progress((index + 1) / total)
                            status_text.text(f"🚀 Memproses baris {index+1} dari {total} (Paralel OSRM)...")
                            
                            try: r_lat, r_lon = float(row[b_lat]), float(row[b_lon])
                            except: 
                                results.append({"NAMA_TARGET": row[b_name], "STATUS": "Invalid Data"})
                                continue

                            # 1. Sync Nominatim (Wajib 1 detik delay untuk anti-ban)
                            addr, kel, kec, kab = cari_alamat(r_lat, r_lon)
                            await asyncio.sleep(1.05) 
                            
                            quad = "Manual"
                            m_q = df_quad[(df_quad[q_kel].astype(str).str.contains(kel, case=False, na=False)) & (df_quad[q_kec].astype(str).str.contains(kec, case=False, na=False))]
                            if not m_q.empty: quad = str(m_q.iloc[0][q_res])

                            row_data = {"NAMA_TARGET": row[b_name], "LATITUDE": r_lat, "LONGITUDE": r_lon, "KECAMATAN": kec, "KOTA": kab, "QUADRAN": quad}
                            catchment_summary, total_in_radius = analyze_catchment_area(df_master, r_lat, r_lon, batch_radius, m_lat, m_lon, m_seg, m_id, m_name)
                            row_data[f"TOTAL_RADIUS_{batch_radius}KM"] = total_in_radius

                            # 2. ASYNC OSRM GATHERING (Tembak semua segmen serentak)
                            osrm_tasks = []
                            matches_dict = {}
                            
                            for s in list_segmen:
                                match_s = get_best_match(df_master, r_lat, r_lon, s, m_seg, m_lat, m_lon, m_id, m_name)
                                if match_s:
                                    matches_dict[s] = match_s
                                    # Create coroutine
                                    osrm_tasks.append(fetch_osrm_async(session, r_lat, r_lon, match_s['lat'], match_s['lon'], s))
                                else:
                                    matches_dict[s] = None
                            
                            # Jalankan semua request OSRM baris ini secara berbarengan (paralel)
                            osrm_results = await asyncio.gather(*osrm_tasks)
                            
                            # 3. Susun Hasil
                            for s_name, d_km, t_min in osrm_results:
                                ms = matches_dict[s_name]
                                row_data[f"TERDEKAT_{s_name}_ID"] = ms['id']
                                row_data[f"TERDEKAT_{s_name}_NAMA"] = ms['nama']
                                row_data[f"[{s_name}] UDARA (KM)"] = ms['jarak_udara']
                                row_data[f"[{s_name}] DARAT (KM)"] = d_km
                                row_data[f"[{s_name}] MENIT"] = t_min
                                
                                # Extra data (Avg SPS dll)
                                for ex_k, ex_v in ms['extra_data'].items():
                                    row_data[f"[{s_name}] {ex_k}"] = ex_v
                                    
                            results.append(row_data)

                # Jalankan Asyncio Loop dalam Streamlit
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                loop.run_until_complete(run_batch_processing())
                loop.close()

                # TAMPILKAN HASIL DENGAN AG-GRID ENTERPRISE TABLE
                df_final = pd.DataFrame(results)
                status_text.empty()
                progress_bar.empty()
                st.success(f"Berhasil memproses {total} baris dengan mesin Async!")
                
                # Ag-Grid Config
                gb = GridOptionsBuilder.from_dataframe(df_final)
                gb.configure_pagination(paginationAutoPageSize=True)
                gb.configure_side_bar()
                gb.configure_default_column(filterable=True, sortable=True, resizable=True)
                gridOptions = gb.build()
                AgGrid(df_final, gridOptions=gridOptions, enable_enterprise_modules=False, height=400, theme="balham")

                # Ekspor Excel
                output = BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: df_final.to_excel(writer, index=False, sheet_name='Hasil_Async_Analysis')
                st.download_button("Unduh Excel Laporan Lengkap (.xlsx)", data=output.getvalue(), file_name="GeoMarketing_Async_Output.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
