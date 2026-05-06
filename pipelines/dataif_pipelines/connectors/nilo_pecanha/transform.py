from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FieldMapping:
    column_name: str
    source_headers: tuple[str, ...]


@dataclass(frozen=True)
class DomainSpec:
    label: str
    domain_key: str
    raw_table_name: str
    field_mappings: tuple[FieldMapping, ...]

    @property
    def raw_column_names(self) -> tuple[str, ...]:
        return tuple(item.column_name for item in self.field_mappings)

    @property
    def source_headers(self) -> tuple[str, ...]:
        return tuple(item.source_headers[0] for item in self.field_mappings)


ACADEMIC_FIELD_MAPPINGS = (
    FieldMapping("ano", ("Ano",)),
    FieldMapping("carga_horaria", ("Carga Horaria",)),
    FieldMapping("carga_horaria_minima", ("Carga Horaria Mínima",)),
    FieldMapping("categoria_da_situacao", ("Categoria da Situação",)),
    FieldMapping("co_inst", ("Co Inst",)),
    FieldMapping("cod_unidade", ("Cod Unidade",)),
    FieldMapping("cor_raca", ("Cor / Raça",)),
    FieldMapping("codigo_da_matricula", ("Código da Matricula", "Código da Matrícula")),
    FieldMapping("codigo_da_unidade_de_ensino_sistec", ("Código da Unidade de Ensino - SISTEC",)),
    FieldMapping("codigo_do_ciclo_matricula", ("Código do Ciclo Matricula",)),
    FieldMapping("codigo_do_municipio_com_dv", ("Código do Município com DV",)),
    FieldMapping("data_de_fim_previsto_do_ciclo", ("Data de Fim Previsto do Ciclo",)),
    FieldMapping("data_de_inicio_do_ciclo", ("Data de Inicio do Ciclo",)),
    FieldMapping("data_de_ocorrencia_da_matricula", ("Data de Ocorrencia da Matricula",)),
    FieldMapping("eixo_tecnologico", ("Eixo Tecnológico",)),
    FieldMapping("faixa_etaria", ("Faixa Etária",)),
    FieldMapping("fator_esforco_curso", ("Fator Esforço Curso",)),
    FieldMapping("fonte_de_financiamento", ("Fonte de Financiamento",)),
    FieldMapping("forma_de_ingresso", ("Forma de ingresso",)),
    FieldMapping("habilitacao", ("Habilitação",)),
    FieldMapping("idade", ("Idade",)),
    FieldMapping("instituicao", ("Instituição",)),
    FieldMapping("matricula_atendida", ("Matrícula Atendida",)),
    FieldMapping("modalidade_de_ensino", ("Modalidade de Ensino",)),
    FieldMapping("municipio", ("Município",)),
    FieldMapping("mes_de_ocorrencia_da_situacao", ("Mês De Ocorrência da Situação",)),
    FieldMapping("nome_de_curso", ("Nome de Curso",)),
    FieldMapping("regiao", ("Região",)),
    FieldMapping("renda_familiar", ("Renda Familiar",)),
    FieldMapping("sexo", ("Sexo",)),
    FieldMapping("situacao_de_matricula", ("Situação de Matrícula",)),
    FieldMapping("subeixo_tecnologico", ("Subeixo Tecnológico",)),
    FieldMapping("tipo_de_curso", ("Tipo de Curso",)),
    FieldMapping("tipo_de_oferta", ("Tipo de Oferta",)),
    FieldMapping("total_de_inscritos", ("Total de Inscritos",)),
    FieldMapping("turno", ("Turno",)),
    FieldMapping("uf", ("UF",)),
    FieldMapping("unidade_de_ensino", ("Unidade de Ensino",)),
    FieldMapping("vagas_extraordinarias_ac", ("Vagas Extraordinárias AC",)),
    FieldMapping("vagas_extraordinarias_l1", ("Vagas Extraordinárias l1",)),
    FieldMapping("vagas_extraordinarias_l10", ("Vagas Extraordinárias l10",)),
    FieldMapping("vagas_extraordinarias_l13", ("Vagas Extraordinárias l13",)),
    FieldMapping("vagas_extraordinarias_l14", ("Vagas Extraordinárias l14",)),
    FieldMapping("vagas_extraordinarias_l2", ("Vagas Extraordinárias l2",)),
    FieldMapping("vagas_extraordinarias_l5", ("Vagas Extraordinárias l5",)),
    FieldMapping("vagas_extraordinarias_l6", ("Vagas Extraordinárias l6",)),
    FieldMapping("vagas_extraordinarias_l9", ("Vagas Extraordinárias l9",)),
    FieldMapping("vagas_extraordinarias_lb_ppi", ("Vagas Extraordinárias LB_PPI",)),
    FieldMapping("vagas_extraordinarias_lb_q", ("Vagas Extraordinárias LB_Q",)),
    FieldMapping("vagas_extraordinarias_lb_pcd", ("Vagas Extraordinárias LB_PCD",)),
    FieldMapping("vagas_extraordinarias_lb_ep", ("Vagas Extraordinárias LB_EP",)),
    FieldMapping("vagas_extraordinarias_li_ppi", ("Vagas Extraordinárias LI_PPI",)),
    FieldMapping("vagas_extraordinarias_li_q", ("Vagas Extraordinárias LI_Q",)),
    FieldMapping("vagas_extraordinarias_li_pcd", ("Vagas Extraordinárias LI_PCD",)),
    FieldMapping("vagas_extraordinarias_li_ep", ("Vagas Extraordinárias LI_EP",)),
    FieldMapping("vagas_ofertadas", ("Vagas Ofertadas",)),
    FieldMapping("vagas_regulares_ac", ("Vagas Regulares AC",)),
    FieldMapping("vagas_regulares_l1", ("Vagas Regulares l1",)),
    FieldMapping("vagas_regulares_l10", ("Vagas Regulares l10",)),
    FieldMapping("vagas_regulares_l13", ("Vagas Regulares l13",)),
    FieldMapping("vagas_regulares_l14", ("Vagas Regulares l14",)),
    FieldMapping("vagas_regulares_l2", ("Vagas Regulares l2",)),
    FieldMapping("vagas_regulares_l5", ("Vagas Regulares l5",)),
    FieldMapping("vagas_regulares_l6", ("Vagas Regulares l6",)),
    FieldMapping("vagas_regulares_l9", ("Vagas Regulares l9",)),
    FieldMapping("vagas_regulares_lb_ppi", ("Vagas Regulares LB_PPI",)),
    FieldMapping("vagas_regulares_lb_q", ("Vagas Regulares LB_Q",)),
    FieldMapping("vagas_regulares_lb_pcd", ("Vagas Regulares LB_PCD",)),
    FieldMapping("vagas_regulares_lb_ep", ("Vagas Regulares LB_EP",)),
    FieldMapping("vagas_regulares_li_ppi", ("Vagas Regulares LI_PPI",)),
    FieldMapping("vagas_regulares_li_q", ("Vagas Regulares LI_Q",)),
    FieldMapping("vagas_regulares_li_pcd", ("Vagas Regulares LI_PCD",)),
    FieldMapping("vagas_regulares_li_ep", ("Vagas Regulares LI_EP",)),
)

FINANCEIRO_FIELD_MAPPINGS = (
    FieldMapping("uo", ("UO",)),
    FieldMapping("nome_uo", ("nomeUO",)),
    FieldMapping("cod_acao", ("codAcao",)),
    FieldMapping("nome_acao", ("nomeAcao",)),
    FieldMapping("grupo_despesa", ("GrupoDespesa",)),
    FieldMapping("liquidacoes_totais", ("liquidacoesTotais",)),
)

SERVIDORES_FIELD_MAPPINGS = (
    FieldMapping("classe", ("Classe",)),
    FieldMapping("cod_unidade", ("Cod_Unidade",)),
    FieldMapping("codigo_da_unidade_de_ensino_sistec", ("Código_da_Unidade_de_Ensino___SISTEC",)),
    FieldMapping("codigo_municipio_com_dv", ("Código_Municipio_com_DV",)),
    FieldMapping("instituicao", ("Instituição",)),
    FieldMapping("jornada_de_trabalho", ("Jornada_de_Trabalho",)),
    FieldMapping("matricula", ("Matrícula",)),
    FieldMapping("municipio", ("Município",)),
    FieldMapping("regiao", ("Região",)),
    FieldMapping("rsc", ("RSC",)),
    FieldMapping("titulacao", ("Titulação",)),
    FieldMapping("unidade_de_lotacao", ("Unidade_de_Lotação",)),
    FieldMapping("vinculo_carreira", ("Vinculo_Carreira",)),
    FieldMapping("vinculo_contrato", ("Vinculo_Contrato",)),
    FieldMapping("vinculo_professor", ("Vinculo_Professor",)),
    FieldMapping("numero_de_registros", ("Número_de_registros",)),
)

DOMAIN_SPECS = {
    "Matrículas": DomainSpec(
        label="Matrículas",
        domain_key="matriculas",
        raw_table_name="pnp_matriculas_src",
        field_mappings=ACADEMIC_FIELD_MAPPINGS,
    ),
    "Eficiência Acadêmica": DomainSpec(
        label="Eficiência Acadêmica",
        domain_key="eficiencia_academica",
        raw_table_name="pnp_eficiencia_academica_src",
        field_mappings=ACADEMIC_FIELD_MAPPINGS,
    ),
    "Financeiro": DomainSpec(
        label="Financeiro",
        domain_key="financeiro",
        raw_table_name="pnp_financeiro_src",
        field_mappings=FINANCEIRO_FIELD_MAPPINGS,
    ),
    "Servidores": DomainSpec(
        label="Servidores",
        domain_key="servidores",
        raw_table_name="pnp_servidores_src",
        field_mappings=SERVIDORES_FIELD_MAPPINGS,
    ),
}


def _to_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        text = str(value).strip().replace(".", "").replace(",", ".")
        return float(text)
    except (TypeError, ValueError):
        return None


def normalize_record(
    payload: dict[str, Any],
    source_url: str,
    run_id: str,
    endpoint_id: int = 0,
    endpoint_key: str = "default",
    source_kind: str = "api",
) -> dict[str, Any]:
    source_record_id = str(
        payload.get("id")
        or payload.get("_id")
        or payload.get("codigo")
        or payload.get("cod")
        or payload.get("uuid")
        or ""
    )

    serialized = json.dumps(
        {
            "endpoint_id": endpoint_id,
            "source_url": source_url,
            "payload": payload,
        },
        sort_keys=True,
        ensure_ascii=True,
    )
    payload_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()

    return {
        "run_id": run_id,
        "endpoint_id": endpoint_id,
        "endpoint_key": endpoint_key,
        "source_kind": source_kind,
        "source_url": source_url,
        "source_record_id": source_record_id or None,
        "dataset": str(payload.get("dataset") or payload.get("base") or endpoint_key or "nilo_pecanha"),
        "entidade": str(
            payload.get("entidade")
            or payload.get("instituicao")
            or payload.get("municipio")
            or payload.get("nome")
            or ""
        )
        or None,
        "ano": _to_int(payload.get("ano") or payload.get("year")),
        "indicador": str(payload.get("indicador") or payload.get("metric") or payload.get("tipo") or "") or None,
        "valor": _to_float(payload.get("valor") or payload.get("value")),
        "payload_hash": payload_hash,
        "payload": payload,
    }


def normalize_column_name(value: str) -> str:
    ascii_text = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower().strip()
    collapsed = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return collapsed or "coluna"


def domain_spec_for_label(label: str) -> DomainSpec:
    try:
        return DOMAIN_SPECS[label]
    except KeyError as exc:
        raise KeyError(f"Unsupported PNP microdados domain: {label}") from exc


def _coalesce_payload_value(payload: dict[str, Any], headers: tuple[str, ...]) -> str | None:
    for header in headers:
        value = payload.get(header)
        if value is None:
            continue
        if isinstance(value, str):
            return value.strip() or None
        return str(value)
    return None


def normalize_domain_record(
    payload: dict[str, Any],
    *,
    run_id: str,
    instance_key: str | None,
    source_url: str,
) -> dict[str, Any]:
    tipo_microdados = str(payload.get("tipo_microdados") or payload.get("tipo") or "").strip()
    if not tipo_microdados:
        raise KeyError("payload is missing tipo_microdados")

    domain_spec = domain_spec_for_label(tipo_microdados)
    field_values = {
        mapping.column_name: _coalesce_payload_value(payload, mapping.source_headers)
        for mapping in domain_spec.field_mappings
    }

    return {
        "run_id": run_id,
        "instance_key": instance_key,
        "tipo_microdados": tipo_microdados,
        "domain_key": domain_spec.domain_key,
        "raw_table_name": domain_spec.raw_table_name,
        "source_url": source_url,
        "source_record_id": str(payload.get("id") or "").strip() or None,
        "source_row_number": _to_int(payload.get("source_row_number")),
        "source_file_name": str(payload.get("source_file_name") or "").strip() or None,
        "source_file_sha256": str(payload.get("source_file_sha256") or "").strip() or None,
        "ano_base": str(payload.get("ano") or payload.get("Ano") or "").strip() or None,
        "record_hash": normalize_record(
            payload=payload,
            source_url=source_url,
            run_id=run_id,
        )["payload_hash"],
        "field_values": field_values,
    }
