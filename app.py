import streamlit as st
import pandas as pd
import requests
import math
from io import BytesIO
import folium
from streamlit_folium import st_folium
import plotly.express as px

# -------------------------------------------------------------
# 1. KONFIGURASI HALAMAN & CUSTOM CSS
# -------------------------------------------------------------
st.set_page_config(page_title="Spatial Analyzer", layout="wide")

st.markdown("""
<style>
    .block-container { padding-top: 2rem; max-width: 1200px; }
    .notion-h1 { font-size: 2.2rem; font-weight: 700; color: var(--text-color); margin-bottom: 0.2rem; letter-spacing: -0.02em; }
    .notion-sub { font-size: 0.95rem; color: var(--text-color); opacity: 0.6; margin-bottom: 2rem; padding-bottom: 1rem; border-bottom: 1px solid var(--border-color); }
    .notion-callout { display: flex; flex-direction: column; padding: 20px; background-color: var(--secondary-background-color); border-radius: 4px; border: 1px solid var(--border-color); margin-bottom: 24px; border-left: 4px solid var(--text-color); }
    .card-prop-name { font-size: 0.75rem; color: var(--text-color); opacity: 0.5; margin-bottom: 4px; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 600;}
    [data-testid="column"]:nth-of-type(2) {
        position: sticky;
        top: 3rem;
        height: calc(100vh - 3rem);
        overflow-y: auto;
    }
    [data-testid="column"]:nth-of-type(2)::-webkit-scrollbar { display: none; }
    .extra-data-row { display: flex; justify-content: space-between; border-bottom: 1px dashed var(--border-color); padding: 6px 0; font-size: 0.85rem; }
    .extra-data-row:last-child { border-bottom: none; }
</style>
""", unsafe_allow_html=True)

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = None

# -------------------------------------------------------------
# 2. KONSTANTA KOLOM
# -------------------------------------------------------------
COL_ID = "ID_PELANGGAN"
COL_NAME = "NAMA_PELANGGAN"
COL_SEG = "SEGMEN"
COL_STATUS = "STATUS_PELANGGAN"
COL_LAT = "LATITUDE"
COL_LON = "LONGITUDE"

# -------------------------------------------------------------
# 3. FUNGSI DATA LOADING
# -------------------------------------------------------------
@st.cache_data(show_spinner="Memuat data quadran...")
def load_quadran_data():
    df = pd.read_excel("Quadran.xlsx", sheet_name=0)
    df.columns = df.columns.astype(str).str.strip().str.upper()
    for col in ['KELURAHAN', 'KECAMATAN', 'KAB_KOT', 'PROVINCE']:
        if col in df.columns:
            df[col] = df[col].astype(str).str.strip().str.upper()
    return df

def load_master(file_source):
    df = pd.read_excel(file_source, sheet_name=0)
    df.columns = df.columns.astype(str).str.strip().str.upper()
    if COL_STATUS in df.columns:
        df[COL_STATUS] = df[COL_STATUS].astype(str).str.strip().str.upper()
    if COL_SEG in df.columns:
        df[COL_SEG] = df[COL_SEG].astype(str).str.strip().str.upper()
    # Drop rows tanpa koordinat
    df = df.dropna(subset=[COL_LAT, COL_LON])
    return df

# -------------------------------------------------------------
# 4. FUNGSI LOGIKA
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
            kel = addr.get("village", addr.get("suburb", addr.get("neighbourhood", "Tidak diketahui")))
            kec = addr.get("town", addr.get("district", addr.get("city_district", "Tidak diketahui")))
            kab = addr.get("city", addr.get("county", addr.get("region", "Tidak diketahui")))
            return kel, kec, kab
    except:
        pass
    return "Tidak diketahui", "Tidak diketahui", "Tidak diketahui"

def detect_quadran(lat, lon, df_quadran):
    """Deteksi Quadran otomatis dari lat/lon via reverse geocoding + Quadran.xlsx lookup"""
    kel, kec, kab = cari_alamat(lat, lon)
    kel_u = str(kel).strip().upper()
    kec_u = str(kec).strip().upper()

    # Priority 1: Exact match KELURAHAN
    match = df_quadran[df_quadran['KELURAHAN'] == kel_u]
    if not match.empty:
        return match.iloc[0]['QUADRAN'], kel, kec, kab

    # Priority 2: Contains match KELURAHAN
    if kel_u != "TIDAK DIKETAHUI":
        match = df_quadran[df_quadran['KELURAHAN'].str.contains(kel_u, case=False, na=False)]
        if not match.empty:
            return match.iloc[0]['QUADRAN'], kel, kec, kab

    # Priority 3: Exact match KECAMATAN
    match = df_quadran[df_quadran['KECAMATAN'] == kec_u]
    if not match.empty:
        return match.iloc[0]['QUADRAN'], kel, kec, kab

    # Priority 4: Contains match KECAMATAN
    if kec_u != "TIDAK DIKETAHUI":
        match = df_quadran[df_quadran['KECAMATAN'].str.contains(kec_u, case=False, na=False)]
        if not match.empty:
            return match.iloc[0]['QUADRAN'], kel, kec, kab

    return "N/A", kel, kec, kab

def hitung_jarak_udara(lat1, lon1, lat2, lon2):
    try:
        return math.sqrt((float(lat1) - float(lat2))**2 + (float(lon1) - float(lon2))**2) * 111.12
    except:
        return 999999

def get_best_match(df_seg, lat_val, lon_val):
    """Cari outlet terdekat dari dataframe yang sudah difilter per segmen"""
    if df_seg.empty:
        return None
    df_s = df_seg.copy()
    df_s['tmp_dist'] = df_s.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[COL_LAT], r[COL_LON]), axis=1)
    best = df_s.loc[df_s['tmp_dist'].idxmin()]
    return {
        "id": best[COL_ID], "nama": best[COL_NAME],
        "status": best[COL_STATUS],
        "jarak_udara": round(best['tmp_dist'], 2),
        "lat": float(best[COL_LAT]), "lon": float(best[COL_LON]),
    }

def fetch_osrm(lat1, lon1, lat2, lon2):
    url = f"http://router.project-osrm.org/route/v1/driving/{lon1},{lat1};{lon2},{lat2}?overview=false"
    try:
        res = requests.get(url, timeout=5).json()
        if res.get("code") == "Ok" and res.get("routes"):
            return round(res["routes"][0]["distance"] / 1000, 2), round(res["routes"][0]["duration"] / 60, 1)
    except:
        pass
    return "N/A", "N/A"

def analyze_catchment_area(df_filtered, lat_val, lon_val, radius_km):
    """Hitung outlet dalam radius, group by SEGMEN lalu sub-group by STATUS"""
    df_t = df_filtered.copy()
    df_t['jarak_km'] = df_t.apply(lambda r: hitung_jarak_udara(lat_val, lon_val, r[COL_LAT], r[COL_LON]), axis=1)
    df_in = df_t[df_t['jarak_km'] <= radius_km]

    summary = {}
    for seg in sorted(df_in[COL_SEG].unique()):
        df_seg = df_in[df_in[COL_SEG] == seg]
        status_group = {}
        for status in sorted(df_seg[COL_STATUS].unique()):
            df_st = df_seg[df_seg[COL_STATUS] == status].sort_values('jarak_km')
            daftar = []
            for _, row in df_st.iterrows():
                daftar.append({
                    "id": row[COL_ID], "nama": row[COL_NAME], "status": row[COL_STATUS],
                    "lat": float(row[COL_LAT]), "lon": float(row[COL_LON]),
                    "jarak_udara": round(row['jarak_km'], 2),
                })
            status_group[status] = {"jumlah": len(df_st), "daftar": daftar}
        summary[seg] = status_group
    return summary, len(df_in)

# -------------------------------------------------------------
# 5. SIDEBAR
# -------------------------------------------------------------
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-bottom:8px;'>Database Master</div>", unsafe_allow_html=True)
uploaded_master = st.sidebar.file_uploader("Upload Excel Master (opsional)", type=["xlsx"])

# Load data
try:
    df_quadran = load_quadran_data()
except Exception as e:
    st.error(f"Error memuat Quadran.xlsx: {e}")
    st.stop()

try:
    if uploaded_master:
        df_master_raw = load_master(uploaded_master)
    else:
        df_master_raw = load_master("AO_ALL_Segmen.xlsx")
except Exception as e:
    st.error(f"Error memuat data master: {e}")
    st.stop()

# Filter SEGMEN
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:16px; margin-bottom:8px;'>Filter Segmen</div>", unsafe_allow_html=True)
all_segmen = sorted([s for s in df_master_raw[COL_SEG].dropna().unique().tolist() if s != 'NAN'])
selected_segmen = st.sidebar.multiselect("Pilih Segmen", all_segmen, default=all_segmen, label_visibility="collapsed")

# Filter STATUS_PELANGGAN
st.sidebar.markdown("<div style='font-size: 0.85rem; font-weight: 600; color: var(--text-color); opacity:0.6; text-transform: uppercase; margin-top:16px; margin-bottom:8px;'>Filter Status Pelanggan</div>", unsafe_allow_html=True)
all_status = sorted([s for s in df_master_raw[COL_STATUS].dropna().unique().tolist() if s != 'NAN'])
selected_status = st.sidebar.multiselect("Pilih Status", all_status, default=["ACT"], label_visibility="collapsed")

# Apply filters
df_master = df_master_raw[
    (df_master_raw[COL_SEG].isin(selected_segmen)) &
    (df_master_raw[COL_STATUS].isin(selected_status))
].copy()

st.sidebar.markdown("---")
st.sidebar.markdown(f"<div style='font-size: 0.8rem; opacity: 0.5;'>Data terfilter: <b>{len(df_master):,}</b> outlet</div>", unsafe_allow_html=True)

# Warna segmen
default_colors = ["#2D88FF", "#FF9900", "#00A86B", "#E03E3E", "#6B52D1", "#D9730D", "#F5A623", "#50E3C2"]
segmen_colors = {seg: default_colors[i % len(default_colors)] for i, seg in enumerate(all_segmen)}

# -------------------------------------------------------------
# 6. MAIN UI
# -------------------------------------------------------------
st.markdown("<div class='notion-h1'>Spatial Analytics</div>", unsafe_allow_html=True)
st.markdown("<div class='notion-sub'>Analisa jarak outlet terdekat per segmen dari titik target.</div>", unsafe_allow_html=True)

if df_master.empty:
    st.warning("Tidak ada data setelah filter. Sesuaikan filter Segmen dan Status di sidebar.")
    st.stop()

st.markdown("<div class='card-prop-name'>Parameter Ekspansi</div>", unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns([2, 1.5, 1.5, 1])
in_name = c1.text_input("Nama Target", "Target Baru")
in_lat = c2.text_input("Latitude", "-6.914744")
in_lon = c3.text_input("Longitude", "107.609810")
radius_filter = c4.number_input("Radius (KM)", min_value=0.1, max_value=50.0, value=3.0, step=0.1)

if st.button("Jalankan Analisis", type="primary"):
    with st.spinner("Membangun Dashboard..."):
        lat_v, lon_v = float(in_lat), float(in_lon)

        # Deteksi Quadran dari Quadran.xlsx
        quad, kel, kec, kab = detect_quadran(lat_v, lon_v, df_quadran)

        # Cari terdekat per segmen + OSRM
        active_segmen = [s for s in selected_segmen if s in df_master[COL_SEG].unique()]
        matches = {}
        for seg in active_segmen:
            df_seg = df_master[df_master[COL_SEG] == seg]
            best = get_best_match(df_seg, lat_v, lon_v)
            if best:
                darat, menit = fetch_osrm(lat_v, lon_v, best['lat'], best['lon'])
                best['jarak_darat'] = darat
                best['waktu_tempuh'] = menit
                matches[seg] = best

        # Catchment area
        catchment_summary, total_in_radius = analyze_catchment_area(df_master, lat_v, lon_v, radius_filter)

        st.session_state.analysis_result = {
            "name": in_name, "lat": lat_v, "lon": lon_v, "quad": quad,
            "matches": matches, "catchment": catchment_summary,
            "total_catchment": total_in_radius, "radius_km": radius_filter,
            "admin": {"kel": kel, "kec": kec, "kab": kab},
            "active_segmen": active_segmen,
        }

# --- TAMPILKAN HASIL ---
if st.session_state.analysis_result:
    res = st.session_state.analysis_result
    st.write("---")

    col_list, col_map = st.columns([1.1, 1], gap="large")

    # [KOLOM KIRI]: Info & Daftar Outlet
    with col_list:
        st.markdown(f"""
        <div class="notion-callout" style="margin-bottom: 12px;">
            <strong style="font-size: 1.1rem; display:block; margin-bottom:4px;">{res['name']}</strong>
            <div>
                <span style="font-size: 0.75rem; opacity:0.5; text-transform:uppercase; font-weight:600;">Quadran</span>
                <span style="margin-left: 6px; padding: 2px 10px; background-color: rgba(45,136,255,0.1); color: #2D88FF; border: 1px solid rgba(45,136,255,0.2); border-radius: 4px; font-weight: 600;">{res['quad']}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)

        # Outlet terdekat per segmen
        st.markdown(f"<div class='card-prop-name' style='font-size: 1rem; margin-top: 16px;'>Outlet Terdekat per Segmen</div>", unsafe_allow_html=True)
        for seg in res.get('active_segmen', []):
            if seg in res['matches']:
                m = res['matches'][seg]
                color = segmen_colors.get(seg, '#ccc')
                with st.expander(f"🏷️ {seg} — {m['nama']} ({m['jarak_udara']} KM)", expanded=True):
                    sc1, sc2 = st.columns(2)
                    with sc1:
                        st.markdown(f"**ID:** `{m['id']}`")
                        st.markdown(f"**Status:** {m['status']}")
                        st.markdown(f"**Jarak Udara:** {m['jarak_udara']} KM")
                    with sc2:
                        st.markdown(f"<span style='color:#2D88FF;'>**Jarak Darat:** {m['jarak_darat']} KM</span>", unsafe_allow_html=True)
                        st.markdown(f"<span style='color:#2D88FF;'>**Waktu Tempuh:** {m['waktu_tempuh']} Menit</span>", unsafe_allow_html=True)

        # Catchment area detail (group by SEGMEN → STATUS)
        st.markdown(f"<div class='card-prop-name' style='font-size: 1rem; margin-top: 24px;'>Detail {res['total_catchment']} Outlet dalam Radius {res['radius_km']} KM</div>", unsafe_allow_html=True)
        if res['total_catchment'] == 0:
            st.info("Tidak ada outlet dalam radius ini.")
        else:
            for seg, status_groups in res['catchment'].items():
                total_seg = sum(sg['jumlah'] for sg in status_groups.values())
                st.markdown(f"**🏷️ {seg} ({total_seg} Outlet)**")
                for status, data in status_groups.items():
                    st.markdown(f"*Status: {status} — {data['jumlah']} outlet*")
                    for idx, item in enumerate(data['daftar']):
                        label = f"🥇 {item['nama']} ({item['jarak_udara']} KM)" if idx == 0 else f"📍 {item['nama']} ({item['jarak_udara']} KM)"
                        with st.expander(label, expanded=(idx == 0)):
                            st.markdown(f"**ID:** `{item['id']}` &nbsp; | &nbsp; **Status:** {item['status']} &nbsp; | &nbsp; **Jarak Udara:** {item['jarak_udara']} KM")
                st.write("")

    # [KOLOM KANAN]: Chart & Peta
    with col_map:
        # Donut chart proporsi segmen
        if res['total_catchment'] > 0:
            labels = list(res['catchment'].keys())
            values = [sum(sg['jumlah'] for sg in sgs.values()) for sgs in res['catchment'].values()]
            pie_colors = [segmen_colors.get(l, '#ccc') for l in labels]
            fig = px.pie(names=labels, values=values, hole=0.5, title="Proporsi Segmen dalam Radius")
            fig.update_traces(marker=dict(colors=pie_colors), textinfo='percent+label')
            fig.update_layout(margin=dict(t=40, b=10, l=10, r=10), height=250, showlegend=False)
            st.plotly_chart(fig, use_container_width=True, config={'displayModeBar': False})

        # Folium Map
        m = folium.Map(location=[res['lat'], res['lon']], zoom_start=13, tiles="cartodb positron")
        folium.Circle([res['lat'], res['lon']], radius=res['radius_km'] * 1000, color='#2D88FF', fill=True, fill_opacity=0.1, weight=1).add_to(m)
        folium.Marker([res['lat'], res['lon']], popup="<b>TARGET</b>", icon=folium.Icon(color="black", icon="star")).add_to(m)

        bounds = [[res['lat'], res['lon']]]

        # Plot closest per segmen (garis putus)
        for seg, match in res['matches'].items():
            col_hex = segmen_colors.get(seg, "gray")
            folium.PolyLine([[res['lat'], res['lon']], [match['lat'], match['lon']]], color=col_hex, weight=2, dash_array='4,4').add_to(m)
            popup_html = f"<div style='min-width:150px;'><b>[{seg}] {match['nama']}</b><br>Udara: {match['jarak_udara']} KM<br>Darat: {match['jarak_darat']} KM</div>"
            folium.Marker([match['lat'], match['lon']], popup=folium.Popup(popup_html, max_width=250), icon=folium.Icon(color="lightgray", icon="info-sign")).add_to(m)
            bounds.append([match['lat'], match['lon']])

        # Plot semua outlet dalam radius
        for seg, status_groups in res['catchment'].items():
            for status, data in status_groups.items():
                for item in data['daftar']:
                    folium.CircleMarker(
                        [item['lat'], item['lon']], radius=4, weight=1,
                        color=segmen_colors.get(seg, 'gray'), fill=True, fill_opacity=0.6,
                        popup=f"[{seg}|{item['status']}] {item['nama']}"
                    ).add_to(m)
                    bounds.append([item['lat'], item['lon']])

        if len(bounds) > 1:
            m.fit_bounds(bounds)
        st_folium(m, height=500, use_container_width=True, key="map_dashboard")
