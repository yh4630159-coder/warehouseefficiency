import streamlit as st
import pandas as pd
import altair as alt

# ================= 1. 页面配置 =================
st.set_page_config(page_title="海外仓时效看板 V6.3", page_icon="🚀", layout="wide")
st.markdown("""<style>div[data-testid="stMetricValue"] {font-size: 24px; font-weight: bold;} .block-container {padding-top: 1rem;}</style>""", unsafe_allow_html=True)

# ================= 2. 数据处理核心 =================
@st.cache_data(ttl=3600)
def load_data(uploaded_file):
    try:
        df = pd.read_parquet(uploaded_file)
        
        # 1. 仅做必要的类型恢复 (Parquet通常会保留类型，但为了保险)
        time_cols = ['Time_Audit', 'Time_Shipped', 'Time_Online', 'Time_Delivered']
        for col in time_cols:
            if col in df.columns: df[col] = pd.to_datetime(df[col], errors='coerce')

        # 2. 供应商提取
        if 'Warehouse' in df.columns:
            df['Warehouse'] = df['Warehouse'].astype(str)
            df['Provider'] = df['Warehouse'].apply(lambda x: x.split('-')[0] if '-' in x else x)
        return df
    except Exception as e:
        st.error(f"数据错误: {e}")
        return pd.DataFrame()

# ================= 3. 绘图函数 =================
def plot_bar_chart(data, x_field, y_field, x_title, threshold, label_col, color_reverse=False):
    chart_height = max(len(data) * 40, 400)
    color_logic = alt.condition(alt.datum[x_field] > threshold, alt.value('#d32f2f'), alt.value('#2e7d32')) if color_reverse else alt.condition(alt.datum[x_field] < threshold, alt.value('#d32f2f'), alt.value('#1976d2'))
    
    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X(f'{x_field}:Q', title=x_title),
        y=alt.Y(f'{y_field}:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300, labelFontSize=13)), 
        color=color_logic, tooltip=[f'{y_field}:N', f'{label_col}:N']
    )
    text = bars.mark_text(align='left', baseline='middle', dx=3, fontSize=13, fontWeight='bold').encode(text=alt.Text(f'{label_col}:N'))
    rule = alt.Chart(pd.DataFrame({'x': [threshold]})).mark_rule(color='orange', strokeDash=[5,5]).encode(x='x')
    return (bars + text + rule).properties(height=chart_height)

def get_trend_data(df, date_col, metric_col, granularity, mode='rate'):
    df_chart = df.set_index(date_col).copy()
    rule, fmt = ('W-MON', '%m-%d') if granularity == '周 (Week)' else ('MS', '%Y-%m') if granularity == '月 (Month)' else ('D', '%m-%d')
    
    if mode == 'rate':
        res = df_chart.resample(rule).agg({metric_col: 'sum', 'Order_ID': 'count'})
        res = res[res['Order_ID'] > 0]
        res['Value'] = res[metric_col] / res['Order_ID']
    else:
        res = df_chart.resample(rule)[metric_col].mean().to_frame(name='Value')
    
    res = res.reset_index().rename(columns={date_col: 'Date'}).sort_values('Date')
    
    def fmt_val(val): return f"{val:.1%}" if mode == 'rate' else f"{val:.1f}h"
    
    if granularity == '周 (Week)':
        res['Data_Label'] = "WEEK" + pd.Series(range(1, len(res)+1)).astype(str) + "\n" + res['Value'].apply(fmt_val)
        res['Trend'] = res['Value']
    elif granularity == '月 (Month)':
        res['Data_Label'] = res['Date'].dt.strftime('%Y-%m') + "\n" + res['Value'].apply(fmt_val)
        res['Trend'] = res['Value']
    else:
        res['Data_Label'] = ""
        res['Trend'] = res['Value'].rolling(window=7, min_periods=1).mean()
    return res, fmt

def plot_trend_interactive(data, x_fmt, title, is_percent=True, target_line=None):
    y_format = '.0%' if is_percent else '.1f'
    base = alt.Chart(data).encode(x=alt.X('Date:T', title=None, axis=alt.Axis(format=x_fmt)), tooltip=[alt.Tooltip('Date:T', format='%Y-%m-%d'), alt.Tooltip('Value:Q', title='实际值', format=y_format), alt.Tooltip('Trend:Q', title='趋势', format=y_format)])
    
    line_raw = base.mark_line(color='#90CAF9', strokeDash=[4, 4], opacity=0.6).encode(y=alt.Y('Value:Q', title=title, axis=alt.Axis(format=y_format)))
    line_trend = base.mark_line(color='#1976D2', strokeWidth=3).encode(y=alt.Y('Trend:Q'))
    nearest = alt.selection_point(nearest=True, on='mouseover', fields=['Date'], empty=False)
    selectors = base.mark_point().encode(opacity=alt.value(0)).add_params(nearest)
    points = base.mark_point(filled=True, color='#1976D2', size=50).encode(opacity=alt.condition(nearest, alt.value(1), alt.value(0)), y='Trend:Q')
    rules = base.mark_rule(color='gray').encode(opacity=alt.condition(nearest, alt.value(0.5), alt.value(0)))
    chart = line_raw + line_trend + selectors + points + rules
    
    if 'Data_Label' in data.columns and data['Data_Label'].str.len().sum() > 0:
        chart += base.mark_text(align='center', baseline='bottom', dy=-15, fontSize=14, fontWeight='bold', lineBreak='\n', color='#333333').encode(text='Data_Label', y='Value:Q')
    if target_line is not None:
        chart += alt.Chart(pd.DataFrame({'y': [target_line]})).mark_rule(color='#FF5252', strokeDash=[5,5], strokeWidth=2).encode(y='y')
    return chart.properties(height=300).interactive()

# ================= 4. 主程序 =================
st.title("📊 海外仓时效看板 V6.3")
with st.expander("📂 数据源管理", expanded=True):
    uploaded_file = st.file_uploader("上传 Parquet 文件", type=['parquet'], label_visibility="collapsed")

if uploaded_file:
    df = load_data(uploaded_file)
    if not df.empty:
        st.divider()
        # === 控制台 ===
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            view_mode = st.radio("1. 分析维度", ["按仓库 (Detail)", "按供应商 (Aggregate)", "按物流商 (Carrier)"], horizontal=True)
            group_col = 'Warehouse' if "仓库" in view_mode else 'Provider' if "供应商" in view_mode else 'Carrier'
        with c2:
            min_d, max_d = df['Time_Audit'].min().date(), df['Time_Audit'].max().date()
            date_range = st.date_input("2. 日期范围", value=(min_d, max_d))
        with c3:
            granularity = st.selectbox("3. 趋势粒度", ["天 (Day)", "周 (Week)", "月 (Month)"], index=0)
        with c4:
            countries = sorted(df['Country'].unique())
            sel_ctry = st.multiselect("4. 国家筛选", countries, default=countries)

        cc1, cc2 = st.columns([1, 1])
        with cc1:
            all_carriers = sorted(df['Carrier'].dropna().unique().tolist())
            sel_carrier_global = st.multiselect("5. 全局物流商筛选 (如只看FedEx请勾选)", all_carriers, default=[])
        with cc2:
            all_targets = sorted(df[group_col].dropna().unique().tolist())
            sel_targets = st.multiselect(f"6. 筛选特定{group_col} (Detail)", all_targets, default=[])

        # === 筛选 ===
        mask = (df['Time_Audit'].dt.date >= date_range[0]) & (df['Time_Audit'].dt.date <= date_range[1]) & (df['Country'].isin(sel_ctry))
        if sel_carrier_global: mask = mask & (df['Carrier'].isin(sel_carrier_global))
        df_show = df[mask].copy()
        if sel_targets: df_show = df_show[df_show[group_col].isin(sel_targets)]

        if df_show.empty:
            st.warning("⚠️ 无数据")
            st.stop()
        st.divider()

        # === 模块一：24H 发货 ===
        st.subheader(f"🏭 1. {group_col}作业效率 (24H发货率)")
        stats_ship = df_show.groupby(group_col).agg(Rate=('is_24h_Ship', 'mean'), Count=('is_24h_Ship', 'count')).reset_index()
        stats_ship['Label'] = stats_ship['Rate'].apply(lambda x: f"{x:.1%}") + " | " + stats_ship['Count'].astype(str)
        c1, c2 = st.columns([3, 1])
        with c1: st.altair_chart(plot_bar_chart(stats_ship, 'Rate', group_col, '24H 发货率', 0.75, 'Label'), use_container_width=True)
        with c2:
            tgt = st.selectbox(f"趋势-{group_col}", stats_ship.sort_values('Rate')[group_col], key='s1')
            if tgt:
                d, f = get_trend_data(df_show[df_show[group_col]==tgt], 'Time_Audit', 'is_24h_Ship', granularity, 'rate')
                st.altair_chart(plot_trend_interactive(d, f, '发货率', True, 0.95), use_container_width=True)
        st.divider()

        # === 模块二：48H 上网 ===
        st.subheader(f"🌐 2. {group_col}物流效率 (48H上网率)")
        stats_ol = df_show.groupby(group_col).agg(Rate=('is_48h_Online', 'mean'), Count=('is_48h_Online', 'count')).reset_index()
        stats_ol['Label'] = stats_ol['Rate'].apply(lambda x: f"{x:.1%}") + " | " + stats_ol['Count'].astype(str)
        c1, c2 = st.columns([3, 1])
        with c1: st.altair_chart(plot_bar_chart(stats_ol, 'Rate', group_col, '48H 上网率', 0.90, 'Label'), use_container_width=True)
        with c2:
            tgt = st.selectbox(f"趋势-{group_col}", stats_ol.sort_values('Rate')[group_col], key='s2')
            if tgt:
                d, f = get_trend_data(df_show[df_show[group_col]==tgt], 'Time_Audit', 'is_48h_Online', granularity, 'rate')
                st.altair_chart(plot_trend_interactive(d, f, '上网率', True, 0.95), use_container_width=True)
        st.divider()

        # === 模块三：揽收时效 ===
        st.subheader(f"🚛 3. 尾程揽收时效 (Handover)")
        valid_ho = df_show[df_show['Hours_Handover'] > 0]
        if valid_ho.empty: st.warning("无数据")
        else:
            stats_ho = valid_ho.groupby(group_col).agg(Val=('Hours_Handover', 'mean'), Count=('Hours_Handover', 'count')).reset_index()
            stats_ho['Label'] = stats_ho['Val'].apply(lambda x: f"{x:.1f}h") + " | " + stats_ho['Count'].astype(str)
            c1, c2 = st.columns([3, 1])
            with c1: st.altair_chart(plot_bar_chart(stats_ho, 'Val', group_col, '平均耗时(h)', 24, 'Label', True), use_container_width=True)
            with c2:
                tgt = st.selectbox(f"趋势-{group_col}", stats_ho.sort_values('Val', ascending=False)[group_col], key='s3')
                if tgt:
                    d, f = get_trend_data(valid_ho[valid_ho[group_col]==tgt], 'Time_Shipped', 'Hours_Handover', granularity, 'mean')
                    st.altair_chart(plot_trend_interactive(d, f, '平均耗时(h)', False, 24), use_container_width=True)
        st.divider()

        # === 模块四：妥投时效 (使用预计算字段) ===
        st.subheader("📦 4. 尾程妥投时效 (Days Transit)")
        # 直接使用 Days_Transit (已在清洗阶段计算：妥投-发货)
        if 'Days_Transit' in df_show.columns:
            valid_otd = df_show[df_show['Days_Transit'].notnull()].copy()
            # 剔除异常值 (比如 > 30天)
            valid_otd = valid_otd[(valid_otd['Days_Transit'] >= 0) & (valid_otd['Days_Transit'] <= 30)]

            if valid_otd.empty:
                st.warning("无有效妥投数据 (请检查源数据是否有签收时间)")
            else:
                # 判断是否只选了 US
                u_ctry = valid_otd['Country'].dropna().unique()
                is_us_mode = (len(sel_ctry)==1 and 'US' in sel_ctry) or (len(u_ctry)==1 and u_ctry[0]=='US')

                if not is_us_mode: # 全球模式
                    st.markdown("##### 🌍 全球/区域概览")
                    c1, c2 = st.columns(2)
                    with c1:
                        s_wh = valid_otd.groupby('Warehouse').agg(Val=('Days_Transit', 'mean'), Count=('Order_ID', 'count')).reset_index()
                        s_wh = s_wh[s_wh['Count']>5].sort_values('Val').head(15)
                        s_wh['Label'] = s_wh['Val'].apply(lambda x: f"{x:.1f}d")
                        st.altair_chart(plot_bar_chart(s_wh, 'Val', 'Warehouse', '天数', 7, 'Label', True), use_container_width=True)
                    with c2:
                        s_car = valid_otd.groupby('Carrier').agg(Val=('Days_Transit', 'mean'), Count=('Order_ID', 'count')).reset_index()
                        s_car = s_car[s_car['Count']>5].sort_values('Val').head(15)
                        s_car['Label'] = s_car['Val'].apply(lambda x: f"{x:.1f}d")
                        st.altair_chart(plot_bar_chart(s_car, 'Val', 'Carrier', '天数', 7, 'Label', True), use_container_width=True)
                else: # US 模式
                    st.markdown("##### 🇺🇸 美国 (US) 深度分析")
                    if 'Province_State' not in valid_otd.columns: st.error("缺州字段")
                    else:
                        c1, c2, c3 = st.columns(3)
                        with c1: sel_wh = st.selectbox("📦 仓库", ['全部'] + sorted(valid_otd['Warehouse'].unique()), key='u1')
                        with c2: sel_car = st.multiselect("🚛 物流商", sorted(valid_otd['Carrier'].unique()), key='u2')
                        with c3: sel_st = st.multiselect("📍 目的州", sorted(valid_otd['Province_State'].dropna().unique()), key='u3')
                        
                        df_u = valid_otd.copy()
                        if sel_wh != '全部': df_u = df_u[df_u['Warehouse'] == sel_wh]
                        if sel_car: df_u = df_u[df_u['Carrier'].isin(sel_car)]
                        if sel_st: df_u = df_u[df_u['Province_State'].isin(sel_st)]
                        
                        if not sel_st: # 热力图
                            st.markdown("**🇺🇸 全美热力图 (Transit Time)**")
                            s_map = df_u.groupby(['Carrier', 'Province_State']).agg(Val=('Days_Transit', 'mean'), C=('Order_ID', 'count')).reset_index()
                            s_map = s_map[s_map['C'] >= 5]
                            if not s_map.empty:
                                base = alt.Chart(s_map).encode(x='Province_State:N', y='Carrier:N')
                                heat = base.mark_rect().encode(color=alt.Color('Val:Q', scale=alt.Scale(scheme='yelloworangered')))
                                txt = base.mark_text().encode(text=alt.Text('Val', format='.1f'), color=alt.value('black'))
                                st.altair_chart((heat+txt).properties(height=350).interactive(), use_container_width=True)
                        else: # 条形图
                            st.markdown(f"**📍 {', '.join(sel_st)} 物流商对比**")
                            s_cmp = df_u.groupby('Carrier').agg(Val=('Days_Transit', 'mean'), C=('Order_ID', 'count')).reset_index()
                            s_cmp['Label'] = s_cmp['Val'].apply(lambda x: f"{x:.1f}d")
                            st.altair_chart(plot_bar_chart(s_cmp, 'Val', 'Carrier', '平均天数', 5, 'Label', True), use_container_width=True)
        else:
            st.info("缺 Days_Transit 字段，请重新运行清洗脚本")
else:
    st.info("👆 请上传数据")