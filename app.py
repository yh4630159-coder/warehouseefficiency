import streamlit as st
import pandas as pd
import altair as alt

# ================= 1. 页面配置 (保持不变) =================
st.set_page_config(
    page_title="海外仓时效看板 V5.9",
    page_icon="🚀",
    layout="wide"
)

# CSS 优化
st.markdown("""
    <style>
        div[data-testid="stMetricValue"] {font-size: 24px; font-weight: bold;}
        .block-container {padding-top: 1rem;}
    </style>
""", unsafe_allow_html=True)

# ================= 2. 数据处理核心 =================

@st.cache_data(ttl=3600)
def load_data(uploaded_file):
    try:
        df = pd.read_parquet(uploaded_file)
        
        # 1. 强制时间清洗
        for col in ['Time_Audit', 'Time_Shipped', 'Time_Online']:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
        
        # 2. 核心指标计算
        if 'Time_Shipped' in df.columns and 'Time_Audit' in df.columns:
            df['Hours_to_Ship'] = (df['Time_Shipped'] - df['Time_Audit']).dt.total_seconds() / 3600
            # 达标判断
            df['is_24h_Ship'] = (df['Hours_to_Ship'] <= 24) & (df['Hours_to_Ship'] > 0)
            
        if 'Time_Online' in df.columns and 'Time_Audit' in df.columns:
            df['Hours_to_Online'] = (df['Time_Online'] - df['Time_Audit']).dt.total_seconds() / 3600
            # 达标判断
            df['is_48h_Online'] = (df['Hours_to_Online'] <= 48) & (df['Hours_to_Online'] > 0)
            
        if 'Time_Online' in df.columns and 'Time_Shipped' in df.columns:
            df['Hours_Handover'] = (df['Time_Online'] - df['Time_Shipped']).dt.total_seconds() / 3600
        else:
            df['Hours_Handover'] = None

        # 3. 供应商提取
        if 'Warehouse' in df.columns:
            df['Warehouse'] = df['Warehouse'].astype(str)
            df['Provider'] = df['Warehouse'].apply(lambda x: x.split('-')[0] if '-' in x else x)

        return df
    except Exception as e:
        st.error(f"数据错误: {e}")
        return pd.DataFrame()

# ================= 3. 绘图函数 (升级版) =================

def plot_bar_v52_style(data, x_field, y_field, x_title, threshold, label_col, color_reverse=False):
    """
    柱状图逻辑 (保持 V5.8 的成功逻辑不变)
    """
    chart_height = max(len(data) * 40, 400)
    
    if color_reverse: # 越低越好
        color_logic = alt.condition(alt.datum[x_field] > threshold, alt.value('#d32f2f'), alt.value('#2e7d32'))
    else: # 越高越好
        color_logic = alt.condition(alt.datum[x_field] < threshold, alt.value('#d32f2f'), alt.value('#1976d2'))

    bars = alt.Chart(data).mark_bar().encode(
        x=alt.X(f'{x_field}:Q', title=x_title),
        y=alt.Y(f'{y_field}:N', sort='-x', title=None, axis=alt.Axis(labelLimit=300, labelFontSize=13)), 
        color=color_logic,
        tooltip=[f'{y_field}:N', f'{label_col}:N']
    )

    text = bars.mark_text(align='left', baseline='middle', dx=3, fontSize=13, fontWeight='bold').encode(
        text=alt.Text(f'{label_col}:N')
    )

    rule = alt.Chart(pd.DataFrame({'x': [threshold]})).mark_rule(color='orange', strokeDash=[5,5]).encode(x='x')

    return (bars + text + rule).properties(height=chart_height)

# ✅ 新增函数：专门处理数据聚合，解决周末跳跃和平均值失真问题
def get_trend_data(df, date_col, metric_col, granularity, mode='rate'):
    """
    mode='rate': 针对0/1值求达标率 (Sum/Count)
    mode='mean': 针对数值求平均值 (Mean)
    """
    df_chart = df.set_index(date_col).copy()
    
    # 1. 确定重采样规则
    if granularity == '周 (Week)':
        rule = 'W-MON'
        fmt = '%m-%d'
    elif granularity == '月 (Month)':
        rule = 'MS'
        fmt = '%Y-%m'
    else:
        rule = 'D'
        fmt = '%m-%d'
        
    # 2. 聚合数据
    if mode == 'rate':
        # 分子分母法：避免平均值失真
        resampled = df_chart.resample(rule).agg({
            metric_col: 'sum',
            'Order_ID': 'count' # 假设有Order_ID列，或者用任意非空列计数
        })
        # 计算比率
        resampled = resampled[resampled['Order_ID'] > 0]
        resampled['Value'] = resampled[metric_col] / resampled['Order_ID']
    else:
        # 直接求平均 (用于耗时时长)
        resampled = df_chart.resample(rule)[metric_col].mean().to_frame(name='Value')
        
    # 3. 计算趋势线 (MA7 - 仅在按天时启用)
    if granularity == '天 (Day)':
        resampled['Trend'] = resampled['Value'].rolling(window=7, min_periods=1).mean()
    else:
        resampled['Trend'] = resampled['Value'] # 周/月无需平滑
        
    return resampled.reset_index().rename(columns={date_col: 'Date'}), fmt

# ✅ 新增函数：交互式折线图，解决数据点密集问题
def plot_trend_interactive(data, x_fmt, title, is_percent=True, target_line=None):
    y_format = '.0%' if is_percent else '.1f'
    
    # 基础图表
    base = alt.Chart(data).encode(
        x=alt.X('Date:T', title=None, axis=alt.Axis(format=x_fmt)),
        tooltip=[
            alt.Tooltip('Date:T', title='日期', format='%Y-%m-%d'),
            alt.Tooltip('Value:Q', title='实际值', format=y_format),
            alt.Tooltip('Trend:Q', title='趋势(均线)', format=y_format)
        ]
    )

    # 1. 虚线 (原始波动)
    line_raw = base.mark_line(
        color='#90CAF9', strokeDash=[4, 4], opacity=0.6
    ).encode(y=alt.Y('Value:Q', title=title, axis=alt.Axis(format=y_format)))

    # 2. 实线 (趋势/均线)
    line_trend = base.mark_line(
        color='#1976D2', strokeWidth=3
    ).encode(y=alt.Y('Trend:Q'))
    
    # 3. 交互层 (鼠标悬停显示)
    # 隐形选择器捕捉鼠标X轴位置
    nearest = alt.selection_point(nearest=True, on='mouseover', fields=['Date'], empty=False)
    
    selectors = base.mark_point().encode(
        opacity=alt.value(0),
    ).add_params(nearest)
    
    # 悬停时显示的点
    points = base.mark_point(filled=True, color='#1976D2', size=50).encode(
        opacity=alt.condition(nearest, alt.value(1), alt.value(0)),
        y='Trend:Q'
    )
    
    # 悬停时显示的垂直线
    rules = base.mark_rule(color='gray').encode(
        opacity=alt.condition(nearest, alt.value(0.5), alt.value(0))
    )
    
    chart = line_raw + line_trend + selectors + points + rules
    
    # 4. 增加基准线 (可选)
    if target_line is not None:
        ref = alt.Chart(pd.DataFrame({'y': [target_line]})).mark_rule(
            color='#FF5252', strokeDash=[5,5]
        ).encode(y='y')
        chart = chart + ref

    return chart.properties(height=300).interactive()

# ================= 4. 主程序 =================

st.title("📊 海外仓时效看板 V5.9 (稳定版)")

with st.expander("📂 数据源管理", expanded=True):
    uploaded_file = st.file_uploader("上传 Parquet 文件", type=['parquet'], label_visibility="collapsed")

if uploaded_file:
    df = load_data(uploaded_file)
    
    if not df.empty:
        st.divider()
        
        # === 全局控制台 ===
        st.markdown("### 🛠️ 全局配置")
        
        # 第一行：基础维度
        c1, c2, c3, c4 = st.columns([1, 1, 1, 1])
        with c1:
            view_mode = st.radio("1. 分析维度", ["按仓库 (Detail)", "按供应商 (Aggregate)"], horizontal=True)
            group_col = 'Warehouse' if "仓库" in view_mode else 'Provider'
        
        with c2:
            min_d, max_d = df['Time_Audit'].min().date(), df['Time_Audit'].max().date()
            date_range = st.date_input("2. 日期范围", value=(min_d, max_d))
        
        with c3:
            granularity = st.selectbox("3. 趋势粒度", ["天 (Day)", "周 (Week)", "月 (Month)"], index=0)
            
        with c4:
            countries = sorted(df['Country'].unique())
            sel_ctry = st.multiselect("4. 国家筛选", countries, default=countries)

        # 第二行：特定对象筛选
        all_targets = sorted(df[group_col].dropna().unique().tolist())
        sel_targets = st.multiselect(f"5. 筛选特定{group_col} (留空则全选)", all_targets, default=[])

        # === 数据过滤逻辑 ===
        mask = (df['Time_Audit'].dt.date >= date_range[0]) & \
               (df['Time_Audit'].dt.date <= date_range[1]) & \
               (df['Country'].isin(sel_ctry))
        df_show = df[mask].copy()
        
        if sel_targets:
            df_show = df_show[df_show[group_col].isin(sel_targets)]

        if df_show.empty:
            st.warning("⚠️ 当前筛选无数据")
            st.stop()
            
        st.divider()

        # =======================================================
        # 模块一：24H 发货效率
        # =======================================================
        st.subheader(f"🏭 1. {group_col}作业效率 (24H发货率)")
        
        stats_ship = df_show.groupby(group_col).agg(
            Rate=('is_24h_Ship', 'mean'),
            Count=('is_24h_Ship', 'count')
        ).reset_index()
        stats_ship['Label'] = stats_ship['Rate'].apply(lambda x: f"{x:.1%}") + " | " + stats_ship['Count'].astype(str) + "单"
        
        col_L1, col_R1 = st.columns([3, 1])
        
        with col_L1:
            if not stats_ship.empty:
                chart = plot_bar_v52_style(stats_ship, 'Rate', group_col, '24H 发货率', 0.75, 'Label')
                st.altair_chart(chart, use_container_width=True)
        
        with col_R1:
            st.info("🔍 **查看趋势**")
            target_list = stats_ship.sort_values('Rate')[group_col].tolist()
            target_ship = st.selectbox(f"选择{group_col}:", target_list, index=0, key="sel_ship")
            
            if target_ship:
                df_target = df_show[df_show[group_col] == target_ship]
                st.markdown(f"**📉 {target_ship}**")
                
                # ✅ 调用新函数处理数据：聚合+MA7
                data_trend, fmt = get_trend_data(df_target, 'Time_Audit', 'is_24h_Ship', granularity, mode='rate')
                
                # ✅ 调用新函数绘图：交互式+基准线
                line = plot_trend_interactive(data_trend, fmt, '发货率', is_percent=True, target_line=0.95)
                
                st.altair_chart(line, use_container_width=True)

        st.divider()

        # =======================================================
        # 模块二：48H 上网效率
        # =======================================================
        st.subheader(f"🌐 2. {group_col}物流效率 (48H上网率)")
        
        stats_ol = df_show.groupby(group_col).agg(
            Rate=('is_48h_Online', 'mean'),
            Count=('is_48h_Online', 'count')
        ).reset_index()
        stats_ol['Label'] = stats_ol['Rate'].apply(lambda x: f"{x:.1%}") + " | " + stats_ol['Count'].astype(str) + "单"

        col_L2, col_R2 = st.columns([3, 1])
        
        with col_L2:
            if not stats_ol.empty:
                chart_ol = plot_bar_v52_style(stats_ol, 'Rate', group_col, '48H 上网率', 0.90, 'Label')
                st.altair_chart(chart_ol, use_container_width=True)
                
        with col_R2:
            st.info("🔍 **查看趋势**")
            target_list_ol = stats_ol.sort_values('Rate')[group_col].tolist()
            target_ol = st.selectbox(f"选择{group_col}:", target_list_ol, index=0, key="sel_online")
            
            if target_ol:
                df_target_ol = df_show[df_show[group_col] == target_ol]
                st.markdown(f"**📉 {target_ol}**")
                
                # ✅ 调用新函数处理数据：注意上网率通常看 'Time_Audit' 或 'Time_Shipped'，这里保持原样用 Audit
                data_trend_ol, fmt = get_trend_data(df_target_ol, 'Time_Audit', 'is_48h_Online', granularity, mode='rate')
                
                # ✅ 调用新函数绘图
                line_ol = plot_trend_interactive(data_trend_ol, fmt, '上网率', is_percent=True, target_line=0.95)
                
                st.altair_chart(line_ol, use_container_width=True)

        st.divider()

        # =======================================================
        # 模块三：FedEx 揽收时效
        # =======================================================
        st.subheader(f"🚛 3. FedEx 揽收时效")
        
        valid_ho = df_show[df_show['Hours_Handover'] > 0]
        
        if valid_ho.empty:
            st.warning("无有效揽收数据")
        else:
            stats_ho = valid_ho.groupby(group_col).agg(
                Val=('Hours_Handover', 'mean'),
                Count=('Hours_Handover', 'count')
            ).reset_index()
            stats_ho['Label'] = stats_ho['Val'].apply(lambda x: f"{x:.1f}h") + " | " + stats_ho['Count'].astype(str) + "单"

            col_L3, col_R3 = st.columns([3, 1])
            
            with col_L3:
                # 注意 reverse=True
                chart_ho = plot_bar_v52_style(stats_ho, 'Val', group_col, '平均耗时(h)', 24, 'Label', color_reverse=True)
                st.altair_chart(chart_ho, use_container_width=True)
                
            with col_R3:
                st.info("🔍 **查看趋势**")
                # 耗时越长越需要关注 (降序)
                target_list_ho = stats_ho.sort_values('Val', ascending=False)[group_col].tolist()
                target_ho = st.selectbox(f"选择{group_col}:", target_list_ho, index=0, key="sel_handover")
                
                if target_ho:
                    df_target_ho = valid_ho[valid_ho[group_col] == target_ho]
                    st.markdown(f"**📉 {target_ho}**")
                    
                    # ✅ 调用新函数处理数据：注意这里是平均值模式(mean)，不是率(rate)
                    # 揽收趋势一般看发货时间 Time_Shipped
                    data_trend_ho, fmt = get_trend_data(df_target_ho, 'Time_Shipped', 'Hours_Handover', granularity, mode='mean')
                    
                    # ✅ 调用新函数绘图：注意不是百分比
                    line_ho = plot_trend_interactive(data_trend_ho, fmt, '平均耗时(h)', is_percent=False, target_line=24)
                    
                    st.altair_chart(line_ho, use_container_width=True)

else:
    st.info("👆 请上传数据")