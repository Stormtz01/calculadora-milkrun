import io
import json
import os
import re
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st

# Só tenta carregar tkinter em ambiente desktop local (nunca em container/nuvem sem DISPLAY)
TEM_TKINTER = False
if os.name == "nt" or os.environ.get("DISPLAY"):
    try:
        import tkinter as tk
        from tkinter import filedialog
        TEM_TKINTER = True
    except Exception:
        TEM_TKINTER = False

st.set_page_config(
    page_title="Calculadora Milk Run - Multi-Transportadoras",
    page_icon="🚚",
    layout="wide",
)

PASTA_PADRAO = Path(__file__).parent / "tabelas"
PASTA_PADRAO.mkdir(exist_ok=True)
ARQUIVO_CONFIG_PASTAS = Path(__file__).parent / ".pastas_recentes.json"

VEICULOS_CONHECIDOS = [
    "FIORINO",
    "PICK-UP",
    "KOMBI",
    "VAN",
    "TRAFIC",
    "SPRINTER",
    "3/4",
    "VUC",
    "MÉDIO",
    "TOCO",
    "TRUCK",
    "BI-TRUCK",
    "CARRETA",
    "CARRETA TRUCADA",
    "CARRETA 24 SIDER",
    "CARRETA 28 SIDER",
]


def _to_float(val, default=0.0) -> float:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return default
    if isinstance(val, (int, float)):
        return float(val)
    s = str(val).strip()
    if not s or s in {"-", "–", "—", "DDR", "N/A", "NAN", "NONE"}:
        return default
    s = s.replace("R$", "").replace("%", "").strip()
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return default


def _parse_faixa_km(texto: str):
    if not texto:
        return None, None
    nums = [int(n) for n in re.findall(r"\d+", str(texto))]
    if len(nums) >= 2:
        return nums[0], nums[1]
    return None, None


def _parse_cap_max(texto: str, default: float = 32000.0) -> float:
    if not texto:
        return default
    s = str(texto).lower().replace(".", "").replace(",", ".")
    nums = [float(n) for n in re.findall(r"\d+(?:\.\d+)?", s)]
    if nums:
        return max(nums)
    return default


def _normalizar_veiculo(nome: str) -> str | None:
    if nome is None or (isinstance(nome, float) and np.isnan(nome)):
        return None
    n = re.sub(r"\s+", " ", str(nome).strip().upper())
    if not n or n in {"NAN", "NONE", "VEÍCULO", "VEICULO", "CAPACIDADE EM KG", "DISTÂNCIAS", "DISTANCIAS", "FAIXA DE KM"}:
        return None

    if re.match(r"^(DE\s+\d|ATÉ\s+\d|ATE\s+\d)", n):
        return None
    if any(k in n for k in ["AJUDANTE", "VALOREM", "GRIS", "SLA", "PERNOITE", "FLUVIAL", "CONFERENTE", "OUTRAS OPERAÇÕES"]):
        return None

    n = n.replace("BI- TRUCK", "BI-TRUCK").replace("BI TRUCK", "BI-TRUCK")
    if "PICK-UP" in n or "PICK UP" in n:
        return "PICK-UP"
    if "KOMBI" in n:
        return "KOMBI"
    if "TRAFIC" in n:
        return "TRAFIC"
    if "SPRINTER" in n:
        return "SPRINTER"
    if n.startswith("MÉDIO") or n.startswith("MEDIO"):
        return "MÉDIO"
    if "CARRETA 24" in n or "24 PALETES" in n:
        return "CARRETA 24 SIDER"
    if "CARRETA 28" in n or "28 PALETES" in n:
        return "CARRETA 28 SIDER"
    if "CARRETA TRUCADA" in n:
        return "CARRETA TRUCADA"
    if n.startswith("CARRETA"):
        return "CARRETA"
    if "BI-TRUCK" in n:
        return "BI-TRUCK"
    if n.startswith("TRUCK"):
        return "TRUCK"
    if n.startswith("TOCO"):
        return "TOCO"
    if n.startswith("VUC"):
        return "VUC"
    if n.startswith("3/4"):
        return "3/4"
    if n.startswith("VAN"):
        return "VAN"
    if n.startswith("FIORINO"):
        return "FIORINO"
    return None


def _extrair_nome_transportadora(nome_arquivo: str) -> str:
    stem = Path(nome_arquivo).stem
    stem_limpo = re.split(r"(?i)\s*[-–]\s*milk\s*run|\s*tabela\s+de\s+pre[cç]os", stem)[0].strip()
    m = re.search(r"(?i)tabela\s+de\s+pre[cç]os\s+(.+)", stem)
    if m:
        parte_pos = re.split(r"(?i)\s*[-–]\s*milk\s*run|\s*[-–]\s*frete\s+dedicado", m.group(1))[0].strip()
        if parte_pos:
            stem_limpo = parte_pos

    tokens = re.sub(r"[_\-]+", " ", stem_limpo).split()
    dedup = []
    for t in tokens:
        if not dedup or dedup[-1].upper() != t.upper():
            dedup.append(t.upper())
    return " ".join(dedup) if dedup else stem.upper()


def _parse_tabela_km_grade(df_raw: pd.DataFrame, nome_transp: str) -> dict:
    linha_veic = None
    linha_sub = None
    for idx in range(min(15, len(df_raw))):
        row_vals = [str(x or "").upper() for x in df_raw.iloc[idx].tolist()]
        row_str = " ".join(row_vals)
        if ("FIORINO" in row_str or "PICK-UP" in row_str or "TOCO" in row_str) and linha_veic is None:
            linha_veic = idx
        if ("FRETE MÍNIMO" in row_str or "FRETE MINIMO" in row_str or "R$/KM" in row_str) and linha_sub is None:
            linha_sub = idx

    if linha_veic is None:
        raise ValueError("Cabeçalho de veículos não encontrado na planilha.")

    slots_veiculos = []
    ncols = df_raw.shape[1]
    for c in range(ncols):
        cell_v = df_raw.iloc[linha_veic, c]
        veic_norm = _normalizar_veiculo(cell_v)
        if not veic_norm:
            continue

        txt_v = str(cell_v).strip()
        cap_max = _parse_cap_max(txt_v, default=np.nan)
        if np.isnan(cap_max) and c + 1 < ncols:
            cap_max = _parse_cap_max(df_raw.iloc[linha_veic, c + 1], default=32000.0)
        if np.isnan(cap_max):
            cap_max = 32000.0

        col_min = None
        col_km = None
        if linha_sub is not None:
            for sc in range(c, min(c + 4, ncols)):
                sub_txt = str(df_raw.iloc[linha_sub, sc] or "").strip().upper()
                if ("FRETE MÍNIMO" in sub_txt or "FRETE MINIMO" in sub_txt) and col_min is None:
                    col_min = sc
                elif "R$/KM" in sub_txt and col_km is None:
                    col_km = sc

        if col_min is None:
            col_min = c
        if col_km is None and col_min + 1 < ncols:
            col_km = col_min + 1

        slots_veiculos.append({
            "veiculo": veic_norm,
            "cap_max_kg": cap_max,
            "col_min": col_min,
            "col_km": col_km,
        })

    col_ajud = col_adv = col_gris = col_sla = col_pern = col_fluv = None
    for r in range(min(12, len(df_raw))):
        for c in range(ncols):
            txt = str(df_raw.iloc[r, c] or "").strip().upper()
            if "AJUDANTE" in txt and col_ajud is None:
                col_ajud = c
            elif ("VALOREM" in txt or "AD VALOREM" in txt) and col_adv is None:
                col_adv = c
            elif "GRIS" in txt and col_gris is None:
                col_gris = c
            elif "SLA" in txt and col_sla is None:
                col_sla = c
            elif "PERNOITE" in txt and col_pern is None:
                col_pern = c
            elif "FLUVIAL" in txt and col_fluv is None:
                col_fluv = c

    inicio_dados = (linha_sub + 1) if linha_sub is not None else (linha_veic + 1)
    linhas = []

    for r in range(inicio_dados, len(df_raw)):
        km_min = km_max = None
        for fc in range(min(4, ncols)):
            cell_faixa = df_raw.iloc[r, fc]
            if pd.notna(cell_faixa) and "DE " in str(cell_faixa).upper() and "KM" in str(cell_faixa).upper():
                km_min, km_max = _parse_faixa_km(cell_faixa)
                break

        if km_min is None or km_max is None:
            continue

        sla_val = _to_float(df_raw.iloc[r, col_sla], 0.0) if col_sla is not None else 0.0
        ajud_val = _to_float(df_raw.iloc[r, col_ajud], 0.0) if col_ajud is not None else 0.0
        adv_val = _to_float(df_raw.iloc[r, col_adv], 0.0) if col_adv is not None else 0.0
        gris_val = _to_float(df_raw.iloc[r, col_gris], 0.0) if col_gris is not None else 0.0
        pern_val = _to_float(df_raw.iloc[r, col_pern], 0.0) if col_pern is not None else 0.0
        fluv_val = _to_float(df_raw.iloc[r, col_fluv], 0.0) if col_fluv is not None else 0.0

        for rr in range(r + 1, min(r + 3, len(df_raw))):
            if sla_val == 0.0 and col_sla is not None:
                sla_val = _to_float(df_raw.iloc[rr, col_sla], 0.0)
            if ajud_val == 0.0 and col_ajud is not None:
                ajud_val = _to_float(df_raw.iloc[rr, col_ajud], 0.0)
            if adv_val == 0.0 and col_adv is not None:
                adv_val = _to_float(df_raw.iloc[rr, col_adv], 0.0)
            if gris_val == 0.0 and col_gris is not None:
                gris_val = _to_float(df_raw.iloc[rr, col_gris], 0.0)

        for slot in slots_veiculos:
            f_min = _to_float(df_raw.iloc[r, slot["col_min"]], np.nan)
            v_km = _to_float(df_raw.iloc[r, slot["col_km"]], 0.0)
            if np.isnan(f_min):
                continue
            linhas.append({
                "transportadora": nome_transp,
                "km_min": km_min,
                "km_max": km_max,
                "sla_dias": int(sla_val),
                "veiculo": slot["veiculo"],
                "cap_max_kg": slot["cap_max_kg"],
                "frete_minimo": f_min,
                "valor_km": v_km,
                "valor_ajudante": ajud_val,
                "perc_ad_valorem": adv_val,
                "perc_gris": gris_val,
                "custo_pernoite": pern_val,
                "custo_fluvial": fluv_val,
            })

    if not linhas:
        raise ValueError("Nenhuma faixa de KM com valores válidos foi encontrada.")

    return {"tipo": "km", "df": pd.DataFrame(linhas)}


def _parse_tabela_hgd(df_raw: pd.DataFrame, nome_transp: str) -> dict:
    linha_veic = None
    linha_cols = None
    for idx in range(min(8, len(df_raw))):
        vals = [str(x or "").strip() for x in df_raw.iloc[idx].tolist()]
        if any("PICK-UP" in v.upper() or "KOMBI" in v.upper() or "TOCO" in v.upper() for v in vals):
            linha_veic = idx
        if any("FRETE R$" in v.upper() for v in vals):
            linha_cols = idx

    if linha_veic is None or linha_cols is None:
        raise ValueError("Estrutura de rotas/veículos da HGD não encontrada.")

    blocos_veic = []
    ncols = df_raw.shape[1]
    for c in range(ncols):
        v_txt = str(df_raw.iloc[linha_veic, c] or "").strip()
        if v_txt and v_txt.upper() != "HGD":
            veic_norm = _normalizar_veiculo(v_txt)
            if not veic_norm:
                continue
            cap_max = _parse_cap_max(v_txt, default=24000.0)
            cols_bloco = {}
            for sc in range(c, min(c + 6, ncols)):
                sub = str(df_raw.iloc[linha_cols, sc] or "").strip().upper()
                if "FRETE R$" in sub:
                    cols_bloco["frete"] = sc
                elif "PEDÁGIO R$ 1/7" in sub or "PEDAGIO R$ 1/7" in sub:
                    cols_bloco["pedagio_reaj"] = sc
                elif "PEDÁGIO" in sub or "PEDAGIO" in sub:
                    cols_bloco["pedagio"] = sc
                elif "TOTAL GERAL" in sub:
                    cols_bloco["total_geral"] = sc
                elif "FRETE AJUSTADO" in sub:
                    cols_bloco["frete_ajustado"] = sc
            if cols_bloco:
                blocos_veic.append({
                    "veiculo": veic_norm,
                    "cap_max_kg": cap_max,
                    "cols": cols_bloco,
                })

    rotas = []
    for r in range(linha_cols + 1, len(df_raw)):
        origem_nome = str(df_raw.iloc[r, 1] or "").strip()
        origem_cid = str(df_raw.iloc[r, 2] or "").strip()
        origem_uf = str(df_raw.iloc[r, 3] or "").strip()
        dest_nome = str(df_raw.iloc[r, 5] or "").strip()
        dest_cid = str(df_raw.iloc[r, 6] or "").strip()
        dest_uf = str(df_raw.iloc[r, 7] or "").strip()

        if not origem_nome or not dest_nome or not dest_cid:
            continue
        if any(p in origem_nome.lower() for p in ["entre ", "outras operações", "outras operacoes", "tipo sider"]):
            continue

        gris_pct = _to_float(df_raw.iloc[r, 9], 0.0)
        adv_pct = _to_float(df_raw.iloc[r, 10], 0.0)

        origem_chave = f"{origem_nome} - {origem_cid}".upper().strip(" -")
        destino_chave = f"{dest_nome} - {dest_cid}".upper().strip(" -")

        for b in blocos_veic:
            cdict = b["cols"]
            frete_val = _to_float(df_raw.iloc[r, cdict["frete"]], np.nan) if "frete" in cdict else np.nan
            ped_val = (
                _to_float(df_raw.iloc[r, cdict["pedagio_reaj"]], np.nan)
                if "pedagio_reaj" in cdict
                else (_to_float(df_raw.iloc[r, cdict["pedagio"]], 0.0) if "pedagio" in cdict else 0.0)
            )
            if pd.isna(ped_val):
                ped_val = _to_float(df_raw.iloc[r, cdict["pedagio"]], 0.0) if "pedagio" in cdict else 0.0
            frete_aj = _to_float(df_raw.iloc[r, cdict["frete_ajustado"]], np.nan) if "frete_ajustado" in cdict else np.nan
            tot_ger = _to_float(df_raw.iloc[r, cdict["total_geral"]], np.nan) if "total_geral" in cdict else np.nan

            if pd.isna(frete_val) and pd.isna(frete_aj) and pd.isna(tot_ger):
                continue

            rotas.append({
                "transportadora": nome_transp,
                "origem": f"{origem_nome} ({origem_cid}/{origem_uf})".strip(),
                "destino": f"{dest_nome} ({dest_cid}/{dest_uf})".strip(),
                "origem_chave": origem_chave,
                "destino_chave": destino_chave,
                "veiculo": b["veiculo"],
                "cap_max_kg": b["cap_max_kg"],
                "frete_base_tab": 0.0 if pd.isna(frete_val) else frete_val,
                "pedagio_tab": 0.0 if pd.isna(ped_val) else ped_val,
                "total_geral_tab": tot_ger,
                "frete_ajustado_tab": frete_aj,
                "perc_gris": gris_pct,
                "perc_ad_valorem": adv_pct,
            })

    if not rotas:
        raise ValueError("Nenhuma rota Origem -> Destino encontrada na HGD.")

    return {"tipo": "rota", "df": pd.DataFrame(rotas)}


def parse_excel_bytes(nome_arquivo: str, fonte_excel):
    nome_transp = _extrair_nome_transportadora(nome_arquivo)
    xls = pd.ExcelFile(fonte_excel)
    sheet = "Atualizada 04.2026 (2)" if "Atualizada 04.2026 (2)" in xls.sheet_names else xls.sheet_names[0]

    df_raw = pd.read_excel(fonte_excel, sheet_name=sheet, header=None)
    header_blob = " ".join(str(x).upper() for x in df_raw.iloc[:6].values.flatten() if pd.notna(x))

    if "GRÁFICAS" in header_blob or "GRAFICAS" in header_blob or "PICK-UP" in header_blob:
        parsed = _parse_tabela_hgd(df_raw, nome_transp)
    else:
        parsed = _parse_tabela_km_grade(df_raw, nome_transp)

    parsed["arquivo"] = nome_arquivo
    parsed["aba"] = sheet
    return nome_transp, parsed


def carregar_pastas_recentes() -> list[str]:
    padrao = [str(PASTA_PADRAO.resolve())]
    if ARQUIVO_CONFIG_PASTAS.exists():
        try:
            salvas = json.loads(ARQUIVO_CONFIG_PASTAS.read_text(encoding="utf-8"))
            for p in salvas:
                if p not in padrao:
                    padrao.append(p)
        except Exception:
            pass
    return padrao


def salvar_pasta_recente(caminho: str) -> None:
    recentes = carregar_pastas_recentes()
    if caminho in recentes:
        recentes.remove(caminho)
    recentes.insert(0, caminho)
    recentes = recentes[:10]
    try:
        ARQUIVO_CONFIG_PASTAS.write_text(
            json.dumps(recentes, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def abrir_dialogo_pasta() -> str | None:
    if not TEM_TKINTER:
        return None
    root = tk.Tk()
    root.withdraw()
    root.attributes("-topmost", True)
    pasta_escolhida = filedialog.askdirectory(
        title="Selecione a pasta com as tabelas das transportadoras (.xlsx)"
    )
    root.destroy()
    return pasta_escolhida or None


@st.cache_data(show_spinner="Carregando tabelas das transportadoras...")
def carregar_transportadoras_da_pasta(caminho_pasta: str) -> tuple[dict[str, dict], list[str]]:
    pasta = Path(caminho_pasta)
    if not pasta.exists() or not pasta.is_dir():
        raise FileNotFoundError(f"A pasta não existe ou não é um diretório válido: {caminho_pasta}")

    arquivos = [p for p in sorted(pasta.glob("*.xlsx")) if not p.name.startswith("~$")]
    tabelas: dict[str, dict] = {}
    erros: list[str] = []

    for arq in arquivos:
        try:
            nome_t, dados_t = parse_excel_bytes(arq.name, arq)
            if nome_t in tabelas:
                nome_t = f"{nome_t} ({arq.stem[:15]})"
            tabelas[nome_t] = dados_t
        except Exception as exc:
            erros.append(f"{arq.name}: {exc}")

    return tabelas, erros


def formatar_brl(valor: float) -> str:
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def calcular_item(
    nome_transp: str,
    tabela_info: dict,
    distancia_km: float,
    peso_kg: float,
    valor_nf: float,
    veiculo: str,
    qtd_ajudantes: int,
    pernoites: int = 0,
    fluvial: int = 0,
    origem_hgd: str | None = None,
    destino_hgd: str | None = None,
    usar_frete_ajustado_hgd: bool = True,
) -> dict:
    veic_norm = _normalizar_veiculo(veiculo) or str(veiculo).strip().upper()
    df = tabela_info["df"]

    if tabela_info["tipo"] == "km":
        filtro = df[
            (df["km_min"] <= distancia_km)
            & (df["km_max"] >= distancia_km)
            & (df["veiculo"] == veic_norm)
        ]
        if filtro.empty:
            return {
                "Transportadora": nome_transp,
                "Tipo Tabela": "Faixa KM",
                "Faixa / Rota": f"{distancia_km:.0f} km",
                "SLA (dias)": "-",
                "Capacidade": "Sem faixa/veículo",
                "Regra": f"Não aplicável ({veic_norm})",
                "Frete Base": None,
                "Extras/Pedágio": None,
                "Ad Valorem + GRIS": None,
                "Total Frete": None,
            }

        row = filtro.iloc[0]
        cap_max = float(row["cap_max_kg"])
        frete_min = float(row["frete_minimo"])
        valor_km = float(row["valor_km"])
        custo_km = distancia_km * valor_km

        if valor_km > 0 and custo_km >= frete_min:
            frete_base = custo_km
            regra = f"KM × R$/Km ({distancia_km:.0f} × {formatar_brl(valor_km)})"
        else:
            frete_base = frete_min
            regra = f"Frete Mínimo ({formatar_brl(frete_min)})"

        custo_ajud = qtd_ajudantes * float(row.get("valor_ajudante", 0.0))
        custo_pern = pernoites * float(row.get("custo_pernoite", 0.0))
        custo_fluv = fluvial * float(row.get("custo_fluvial", 0.0))
        custo_adv = valor_nf * float(row.get("perc_ad_valorem", 0.0))
        custo_gris = valor_nf * float(row.get("perc_gris", 0.0))

        total = frete_base + custo_ajud + custo_pern + custo_fluv + custo_adv + custo_gris
        alerta_cap = "⚠️ Excede cap. kg" if peso_kg > cap_max else "OK"

        return {
            "Transportadora": nome_transp,
            "Tipo Tabela": "Faixa KM",
            "Faixa / Rota": f"{int(row['km_min'])}–{int(row['km_max'])} km",
            "SLA (dias)": int(row.get("sla_dias", 0)),
            "Capacidade": alerta_cap,
            "Regra": regra,
            "Frete Base": round(frete_base, 2),
            "Extras/Pedágio": round(custo_ajud + custo_pern + custo_fluv, 2),
            "Ad Valorem + GRIS": round(custo_adv + custo_gris, 2),
            "Total Frete": round(total, 2),
        }

    filtro = df[
        (df["origem_chave"] == origem_hgd)
        & (df["destino_chave"] == destino_hgd)
        & (df["veiculo"] == veic_norm)
    ]
    if filtro.empty:
        return {
            "Transportadora": nome_transp,
            "Tipo Tabela": "Rota Origem→Destino",
            "Faixa / Rota": f"{origem_hgd or '-'} → {destino_hgd or '-'}",
            "SLA (dias)": "-",
            "Capacidade": "Sem rota/veículo",
            "Regra": f"Não aplicável ({veic_norm})",
            "Frete Base": None,
            "Extras/Pedágio": None,
            "Ad Valorem + GRIS": None,
            "Total Frete": None,
        }

    row = filtro.iloc[0]
    cap_max = float(row["cap_max_kg"])
    if usar_frete_ajustado_hgd and pd.notna(row.get("frete_ajustado_tab")):
        frete_base = float(row["frete_ajustado_tab"])
        pedagio = 0.0
        regra = "FRETE AJUSTADO (tabela)"
    elif pd.notna(row.get("total_geral_tab")):
        frete_base = float(row["total_geral_tab"])
        pedagio = 0.0
        regra = "Total Geral (tabela)"
    else:
        frete_base = float(row["frete_base_tab"])
        pedagio = float(row["pedagio_tab"])
        regra = "Frete R$ + Pedágio"

    custo_adv = valor_nf * float(row.get("perc_ad_valorem", 0.0))
    custo_gris = valor_nf * float(row.get("perc_gris", 0.0))
    total = frete_base + pedagio + custo_adv + custo_gris
    alerta_cap = "⚠️ Excede cap. kg" if peso_kg > cap_max else "OK"

    return {
        "Transportadora": nome_transp,
        "Tipo Tabela": "Rota Origem→Destino",
        "Faixa / Rota": f"{origem_hgd} → {destino_hgd}",
        "SLA (dias)": "-",
        "Capacidade": alerta_cap,
        "Regra": regra,
        "Frete Base": round(frete_base, 2),
        "Extras/Pedágio": round(pedagio, 2),
        "Ad Valorem + GRIS": round(custo_adv + custo_gris, 2),
        "Total Frete": round(total, 2),
    }


# --- Barra Lateral: Pasta Local ou Upload de Tabelas ---
if "pasta_ativa" not in st.session_state:
    st.session_state["pasta_ativa"] = carregar_pastas_recentes()[0]

transportadoras: dict[str, dict] = {}
erros_leitura: list[str] = []

with st.sidebar:
    st.header("📁 Tabelas das Transportadoras")
    fonte_dados = st.radio(
        "Origem das tabelas",
        options=["Pasta local", "Enviar arquivos (.xlsx)"],
        horizontal=True,
    )

    if fonte_dados == "Pasta local":
        pastas_disponiveis = carregar_pastas_recentes()
        pasta_combo = st.selectbox(
            "Pastas recentes",
            options=pastas_disponiveis,
            index=pastas_disponiveis.index(st.session_state["pasta_ativa"])
            if st.session_state["pasta_ativa"] in pastas_disponiveis
            else 0,
        )
        caminho_digitado = st.text_input("Caminho da pasta", value=pasta_combo)

        col_btn1, col_btn2 = st.columns(2)
        with col_btn1:
            if st.button("Carregar pasta", width="stretch"):
                st.session_state["pasta_ativa"] = caminho_digitado.strip()
                salvar_pasta_recente(st.session_state["pasta_ativa"])
                st.cache_data.clear()
                st.rerun()

        with col_btn2:
            if TEM_TKINTER and st.button("Procurar...", width="stretch"):
                escolhida = abrir_dialogo_pasta()
                if escolhida:
                    st.session_state["pasta_ativa"] = escolhida
                    salvar_pasta_recente(escolhida)
                    st.cache_data.clear()
                    st.rerun()

        try:
            transportadoras, erros_leitura = carregar_transportadoras_da_pasta(st.session_state["pasta_ativa"])
        except Exception as erro_pasta:
            st.error(str(erro_pasta))
            st.stop()
    else:
        uploads_tab = st.file_uploader(
            "Selecione uma ou mais planilhas (.xlsx)",
            type=["xlsx"],
            accept_multiple_files=True,
        )
        for up in uploads_tab or []:
            if up.name.startswith("~$"):
                continue
            try:
                nome_t, dados_t = parse_excel_bytes(up.name, io.BytesIO(up.getvalue()))
                if nome_t in transportadoras:
                    nome_t = f"{nome_t} ({Path(up.name).stem[:15]})"
                transportadoras[nome_t] = dados_t
            except Exception as exc:
                erros_leitura.append(f"{up.name}: {exc}")

    st.caption(f"Transportadoras carregadas: **{len(transportadoras)}**")
    for err in erros_leitura:
        st.warning(f"Aviso ao ler {err}")

if not transportadoras:
    st.info("Nenhuma tabela `.xlsx` carregada ainda. Coloque planilhas na pasta ou envie arquivos pela barra lateral.")
    st.stop()

nomes_transp = list(transportadoras.keys())
veiculos_extraidos = {
    v for info in transportadoras.values() for v in info["df"]["veiculo"].dropna().unique() if v
}
veiculos_disponiveis = [v for v in VEICULOS_CONHECIDOS if v in veiculos_extraidos] + sorted(
    veiculos_extraidos - set(VEICULOS_CONHECIDOS)
)

st.title("🚚 Calculadora Milk Run — Multi-Transportadoras")
st.caption("Suporta tabelas por faixa de KM e tabela por rota (ex.: HGD), com uso local ou via GitHub/Web.")

aba_sim, aba_lote, aba_inspecao = st.tabs([
    "Simulador / Comparativo",
    "Cálculo em Lote (.xlsx)",
    "Tabelas Carregadas",
])

with aba_sim:
    col1, col2, col3 = st.columns(3)
    with col1:
        veiculo = st.selectbox("Veículo", options=veiculos_disponiveis)
        distancia_km = st.number_input("Distância Total (KM)", min_value=1.0, max_value=10000.0, value=250.0, step=1.0)
        peso_kg = st.number_input("Peso da Carga (KG)", min_value=0.0, value=450.0, step=10.0)
    with col2:
        valor_nf = st.number_input("Valor da NF / Mercadoria (R$)", min_value=0.0, value=25000.0, step=500.0)
        qtd_ajudantes = st.number_input("Qtd. Ajudantes", min_value=0, max_value=10, value=0, step=1)
        pernoites = st.number_input("Qtd. Pernoites", min_value=0, max_value=10, value=0, step=1)
    with col3:
        fluvial = st.number_input("Qtd. Trechos Fluviais", min_value=0, max_value=10, value=0, step=1)
        modo_selecao = st.radio(
            "Transportadoras",
            options=["Comparar todas", "Escolher uma"],
            horizontal=True,
        )
        escolhida = st.selectbox("Transportadora", options=nomes_transp) if modo_selecao == "Escolher uma" else None

    origens_hgd = []
    for info in transportadoras.values():
        if info["tipo"] == "rota":
            origens_hgd.extend(info["df"]["origem_chave"].dropna().unique().tolist())

    origem_hgd = destino_hgd = None
    usar_frete_ajustado_hgd = True
    if origens_hgd:
        st.markdown("**Seleção de Rota (para tabelas Origem → Destino, ex.: HGD):**")
        c_o, c_d, c_fa = st.columns([2, 2, 1])
        origem_hgd = c_o.selectbox("Origem (HGD)", options=sorted(set(origens_hgd)))
        destinos_filtrados = sorted({
            d
            for info in transportadoras.values()
            if info["tipo"] == "rota"
            for d in info["df"][info["df"]["origem_chave"] == origem_hgd]["destino_chave"].dropna().unique()
        })
        destino_hgd = c_d.selectbox("Destino (HGD)", options=destinos_filtrados or ["-"])
        usar_frete_ajustado_hgd = c_fa.checkbox("Usar FRETE AJUSTADO", value=True)

    alvos = [escolhida] if escolhida else nomes_transp
    st.divider()

    resultados = [
        calcular_item(
            nome,
            transportadoras[nome],
            distancia_km,
            peso_kg,
            valor_nf,
            veiculo,
            qtd_ajudantes,
            pernoites,
            fluvial,
            origem_hgd,
            destino_hgd,
            usar_frete_ajustado_hgd,
        )
        for nome in alvos
    ]
    df_res = pd.DataFrame(resultados)

    df_validos = df_res.dropna(subset=["Total Frete"])
    if not df_validos.empty:
        menor_idx = df_validos["Total Frete"].idxmin()
        st.success(
            f"Menor frete ({veiculo}, {distancia_km:.0f} km): "
            f"**{df_res.loc[menor_idx, 'Transportadora']}** — "
            f"**{formatar_brl(df_res.loc[menor_idx, 'Total Frete'])}**"
        )

    df_exibir = df_res.copy()
    for col_m in ["Frete Base", "Extras/Pedágio", "Ad Valorem + GRIS", "Total Frete"]:
        if col_m in df_exibir.columns:
            df_exibir[col_m] = df_exibir[col_m].apply(
                lambda x: formatar_brl(x) if pd.notnull(x) else "-"
            )

    st.dataframe(df_exibir, width="stretch", hide_index=True)

with aba_lote:
    st.write(
        "Envie um `.xlsx` com colunas: `transportadora`, `veiculo`, `distancia_km`, `peso_kg`, `valor_nf` "
        "(opcionais: `qtd_ajudantes`, `pernoites`, `fluvial`, `origem_chave`, `destino_chave`)."
    )
    arq_lote = st.file_uploader("Upload da planilha de rotas (.xlsx)", type=["xlsx"], key="lote_uploader")
    if arq_lote is not None:
        df_rotas = pd.read_excel(arq_lote)
        saida = []
        for _, r in df_rotas.iterrows():
            t_nome = str(r.get("transportadora", "")).strip().upper()
            if t_nome not in transportadoras:
                saida.append({"Transportadora": t_nome, "Total Frete": None, "Capacidade": "Transportadora não encontrada"})
                continue
            res = calcular_item(
                t_nome,
                transportadoras[t_nome],
                float(r.get("distancia_km", 0.0)),
                float(r.get("peso_kg", 0.0)),
                float(r.get("valor_nf", 0.0)),
                str(r.get("veiculo", "")),
                int(r.get("qtd_ajudantes", 0) or 0),
                int(r.get("pernoites", 0) or 0),
                int(r.get("fluvial", 0) or 0),
                str(r["origem_chave"]).strip().upper() if pd.notna(r.get("origem_chave")) else origem_hgd,
                str(r["destino_chave"]).strip().upper() if pd.notna(r.get("destino_chave")) else destino_hgd,
            )
            saida.append(res)
        st.dataframe(pd.DataFrame(saida), width="stretch", hide_index=True)

with aba_inspecao:
    transp_insp = st.selectbox("Inspecionar tabela carregada", options=nomes_transp)
    info_insp = transportadoras[transp_insp]
    st.caption(f"Arquivo: `{info_insp['arquivo']}` | Aba: `{info_insp['aba']}` | Tipo: `{info_insp['tipo']}`")
    st.dataframe(info_insp["df"].head(30), width="stretch", hide_index=True)