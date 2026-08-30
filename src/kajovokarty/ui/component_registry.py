from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ComponentId(StrEnum):
    APP_WINDOW = 'APP_WINDOW'
    NAV_DASH = 'NAV_DASH'
    NAV_MATCH = 'NAV_MATCH'
    NAV_SEARCH = 'NAV_SEARCH'
    NAV_IMPORT = 'NAV_IMPORT'
    NAV_REPORT = 'NAV_REPORT'
    NAV_AUDIT = 'NAV_AUDIT'
    NAV_SETTINGS = 'NAV_SETTINGS'
    TOP_GLOBAL_SEARCH = 'TOP_GLOBAL_SEARCH'
    TOP_SOURCE_STATUS = 'TOP_SOURCE_STATUS'
    TOP_LAST_RUN = 'TOP_LAST_RUN'
    TOP_RUN_ALL = 'TOP_RUN_ALL'
    TOP_OPERATION_CENTER = 'TOP_OPERATION_CENTER'
    GLOBAL_SELECTION_TRAY = 'GLOBAL_SELECTION_TRAY'
    DASH_CZK = 'DASH_CZK'
    DASH_EUR = 'DASH_EUR'
    DASH_AGING = 'DASH_AGING'
    DASH_OLDEST = 'DASH_OLDEST'
    DASH_LARGEST = 'DASH_LARGEST'
    DASH_FRESHNESS = 'DASH_FRESHNESS'
    MATCH_STATUS_TABS = 'MATCH_STATUS_TABS'
    MATCH_FILTER_BAR = 'MATCH_FILTER_BAR'
    MATCH_DOC_TABLE = 'MATCH_DOC_TABLE'
    MATCH_DOC_ACTIONS = 'MATCH_DOC_ACTIONS'
    MATCH_CANVAS = 'MATCH_CANVAS'
    MATCH_GROUP_CARD = 'MATCH_GROUP_CARD'
    MATCH_CONNECTOR = 'MATCH_CONNECTOR'
    MATCH_SOURCE_TABLE = 'MATCH_SOURCE_TABLE'
    MATCH_SOURCE_TABS = 'MATCH_SOURCE_TABS'
    MATCH_CONTEXT_BAR = 'MATCH_CONTEXT_BAR'
    MATCH_DRAG_GHOST = 'MATCH_DRAG_GHOST'
    MATCH_DROP_PREVIEW = 'MATCH_DROP_PREVIEW'
    MATCH_ALLOC_POPOVER = 'MATCH_ALLOC_POPOVER'
    MATCH_CANDIDATE_PANEL = 'MATCH_CANDIDATE_PANEL'
    MATCH_SCORE_DETAIL = 'MATCH_SCORE_DETAIL'
    MATCH_MANUAL_SETTLEMENT = 'MATCH_MANUAL_SETTLEMENT'
    MATCH_UNDO = 'MATCH_UNDO'
    MATCH_REDO = 'MATCH_REDO'
    MATCH_DETAIL_DRAWER = 'MATCH_DETAIL_DRAWER'
    SEARCH_INPUT = 'SEARCH_INPUT'
    SEARCH_FILTERS = 'SEARCH_FILTERS'
    SEARCH_RESULTS = 'SEARCH_RESULTS'
    SEARCH_RELATIONS = 'SEARCH_RELATIONS'
    IMPORT_API_CARD = 'IMPORT_API_CARD'
    IMPORT_BOOKING_DROP = 'IMPORT_BOOKING_DROP'
    IMPORT_BANK_DROP = 'IMPORT_BANK_DROP'
    IMPORT_QUEUE = 'IMPORT_QUEUE'
    IMPORT_RUNS = 'IMPORT_RUNS'
    IMPORT_RUN_DETAIL = 'IMPORT_RUN_DETAIL'
    IMPORT_QUARANTINE = 'IMPORT_QUARANTINE'
    IMPORT_TYPE_MAPPING = 'IMPORT_TYPE_MAPPING'
    REPORT_SELECTOR = 'REPORT_SELECTOR'
    REPORT_FILTERS = 'REPORT_FILTERS'
    REPORT_TABLE = 'REPORT_TABLE'
    REPORT_EXPORT = 'REPORT_EXPORT'
    AUDIT_FILTERS = 'AUDIT_FILTERS'
    AUDIT_TIMELINE = 'AUDIT_TIMELINE'
    AUDIT_BEFORE_AFTER = 'AUDIT_BEFORE_AFTER'
    AUDIT_OPEN_CURRENT = 'AUDIT_OPEN_CURRENT'
    AUDIT_UNDO = 'AUDIT_UNDO'
    SET_API = 'SET_API'
    SET_SYNC = 'SET_SYNC'
    SET_MATCH = 'SET_MATCH'
    SET_IMPORT = 'SET_IMPORT'
    SET_DATA = 'SET_DATA'
    SET_UI = 'SET_UI'
    GLOBAL_OBJECT_MENU = 'GLOBAL_OBJECT_MENU'
    GLOBAL_TOOLTIP = 'GLOBAL_TOOLTIP'
    GLOBAL_TOAST = 'GLOBAL_TOAST'
    GLOBAL_ERROR_DIALOG = 'GLOBAL_ERROR_DIALOG'
    GLOBAL_PROGRESS = 'GLOBAL_PROGRESS'
    MATCH_COUNTERPARTS_PANEL = 'MATCH_COUNTERPARTS_PANEL'
    MATCH_DATE_WINDOW_CONTROL = 'MATCH_DATE_WINDOW_CONTROL'
    MATCH_AGGREGATE_RECONCILIATION = 'MATCH_AGGREGATE_RECONCILIATION'
    MATCH_REVIEW_BANNER = 'MATCH_REVIEW_BANNER'
    SETTINGS_VALIDATION_SUMMARY = 'SETTINGS_VALIDATION_SUMMARY'


@dataclass(frozen=True, slots=True)
class ComponentSpec:
    component_id: ComponentId
    human_name: str
    view: str
    primary_function: str
    states: tuple[str, ...]


COMPONENT_SPECS: dict[ComponentId, ComponentSpec] = {
    ComponentId.APP_WINDOW: ComponentSpec(ComponentId.APP_WINDOW, 'Hlavní okno', 'Shell', 'Navigace, obnovení rozložení, ukončení', ('normal', 'focus', 'busy', 'error')),
    ComponentId.NAV_DASH: ComponentSpec(ComponentId.NAV_DASH, 'Dashboard', 'Navigace', 'Otevřít Dashboard', ('normal', 'active', 'focus')),
    ComponentId.NAV_MATCH: ComponentSpec(ComponentId.NAV_MATCH, 'Párování', 'Navigace', 'Otevřít Párování', ('normal', 'active', 'focus')),
    ComponentId.NAV_SEARCH: ComponentSpec(ComponentId.NAV_SEARCH, 'Vyhledávání', 'Navigace', 'Otevřít Vyhledávání', ('normal', 'active', 'focus')),
    ComponentId.NAV_IMPORT: ComponentSpec(ComponentId.NAV_IMPORT, 'Importy a synchronizace', 'Navigace', 'Otevřít Importy', ('normal', 'active', 'focus')),
    ComponentId.NAV_REPORT: ComponentSpec(ComponentId.NAV_REPORT, 'Sestavy', 'Navigace', 'Otevřít Sestavy', ('normal', 'active', 'focus')),
    ComponentId.NAV_AUDIT: ComponentSpec(ComponentId.NAV_AUDIT, 'Auditní historie', 'Navigace', 'Otevřít Audit', ('normal', 'active', 'focus')),
    ComponentId.NAV_SETTINGS: ComponentSpec(ComponentId.NAV_SETTINGS, 'Nastavení', 'Navigace', 'Otevřít Nastavení', ('normal', 'active', 'focus')),
    ComponentId.TOP_GLOBAL_SEARCH: ComponentSpec(ComponentId.TOP_GLOBAL_SEARCH, 'Hledat v KájovoKarty', 'Horní lišta', 'Hledat, otevřít výsledek', ('empty', 'typing', 'results', 'error')),
    ComponentId.TOP_SOURCE_STATUS: ComponentSpec(ComponentId.TOP_SOURCE_STATUS, 'Stav zdrojů', 'Horní lišta', 'Otevřít stav zdrojů', ('fresh', 'stale', 'error')),
    ComponentId.TOP_LAST_RUN: ComponentSpec(ComponentId.TOP_LAST_RUN, 'Poslední běh', 'Horní lišta', 'Otevřít detail běhu', ('success', 'warning', 'error')),
    ComponentId.TOP_RUN_ALL: ComponentSpec(ComponentId.TOP_RUN_ALL, 'Aktualizovat a spárovat', 'Horní lišta', 'Spustit celý workflow', ('ready', 'running', 'cancelling', 'error')),
    ComponentId.TOP_OPERATION_CENTER: ComponentSpec(ComponentId.TOP_OPERATION_CENTER, 'Centrum operací', 'Horní lišta', 'Otevřít průběh a zrušit', ('idle', 'running', 'failed', 'completed')),
    ComponentId.GLOBAL_SELECTION_TRAY: ComponentSpec(ComponentId.GLOBAL_SELECTION_TRAY, 'Pracovní výběr', 'Spodní lišta', 'Přidat, odebrat, otevřít v párování', ('collapsed', 'open', 'mixed-currency')),
    ComponentId.DASH_CZK: ComponentSpec(ComponentId.DASH_CZK, 'Přehled CZK', 'Dashboard', 'Drill-down KPI', ('loading', 'ready', 'empty', 'error')),
    ComponentId.DASH_EUR: ComponentSpec(ComponentId.DASH_EUR, 'Přehled EUR', 'Dashboard', 'Drill-down KPI', ('loading', 'ready', 'empty', 'error')),
    ComponentId.DASH_AGING: ComponentSpec(ComponentId.DASH_AGING, 'Stáří rozdílů', 'Dashboard', 'Filtrovat podle stáří', ('ready', 'empty')),
    ComponentId.DASH_OLDEST: ComponentSpec(ComponentId.DASH_OLDEST, 'Nejstarší rozdíly', 'Dashboard', 'Objektové akce', ('ready', 'empty')),
    ComponentId.DASH_LARGEST: ComponentSpec(ComponentId.DASH_LARGEST, 'Největší rozdíly', 'Dashboard', 'Objektové akce', ('ready', 'empty')),
    ComponentId.DASH_FRESHNESS: ComponentSpec(ComponentId.DASH_FRESHNESS, 'Aktuálnost zdrojů', 'Dashboard', 'Otevřít zdrojový běh', ('fresh', 'stale', 'error')),
    ComponentId.MATCH_STATUS_TABS: ComponentSpec(ComponentId.MATCH_STATUS_TABS, 'Stavové záložky', 'Párování', 'Filtrovat stav', ('active', 'inactive')),
    ComponentId.MATCH_FILTER_BAR: ComponentSpec(ComponentId.MATCH_FILTER_BAR, 'Filtry párování', 'Párování', 'Filtrovat/vymazat', ('clean', 'filtered', 'invalid')),
    ComponentId.MATCH_DOC_TABLE: ComponentSpec(ComponentId.MATCH_DOC_TABLE, 'Doklady k vyřešení', 'Párování', 'Výběr, drag, objektové akce', ('loading', 'ready', 'empty', 'error')),
    ComponentId.MATCH_DOC_ACTIONS: ComponentSpec(ComponentId.MATCH_DOC_ACTIONS, 'Akce dokladu', 'Párování', 'ActionRegistry', ('enabled', 'disabled', 'reason')),
    ComponentId.MATCH_CANVAS: ComponentSpec(ComponentId.MATCH_CANVAS, 'Vyrovnávací skupiny', 'Párování', 'Drop, výběr skupiny a vazby', ('empty', 'ready', 'drag-target', 'error')),
    ComponentId.MATCH_GROUP_CARD: ComponentSpec(ComponentId.MATCH_GROUP_CARD, 'Vyrovnávací skupina', 'Párování', 'Upravit, vyřešit, rozpojit', ('balanced', 'partial', 'conflict', 'manual')),
    ComponentId.MATCH_CONNECTOR: ComponentSpec(ComponentId.MATCH_CONNECTOR, 'Vazba s částkou', 'Párování', 'Vybrat, editovat, rozpojit', ('normal', 'hover', 'selected', 'conflict')),
    ComponentId.MATCH_SOURCE_TABLE: ComponentSpec(ComponentId.MATCH_SOURCE_TABLE, 'Zdroje úhrad', 'Párování', 'Výběr, drag, objektové akce', ('loading', 'ready', 'empty', 'error')),
    ComponentId.MATCH_SOURCE_TABS: ComponentSpec(ComponentId.MATCH_SOURCE_TABS, 'Typ zdroje', 'Párování', 'Vše/Booking/Karty/Ruční', ('active', 'inactive')),
    ComponentId.MATCH_CONTEXT_BAR: ComponentSpec(ComponentId.MATCH_CONTEXT_BAR, 'Příkazová lišta výběru', 'Párování', 'Spárovat, rozdělit, vyřešit', ('hidden', 'visible', 'disabled')),
    ComponentId.MATCH_DRAG_GHOST: ComponentSpec(ComponentId.MATCH_DRAG_GHOST, 'Náhled tažených položek', 'Párování', 'Informace o výběru', ('single', 'multi', 'mixed-currency')),
    ComponentId.MATCH_DROP_PREVIEW: ComponentSpec(ComponentId.MATCH_DROP_PREVIEW, 'Náhled dopadu', 'Párování', 'Přesná/částečná/zakázaná vazba', ('allowed', 'partial', 'blocked', 'conflict')),
    ComponentId.MATCH_ALLOC_POPOVER: ComponentSpec(ComponentId.MATCH_ALLOC_POPOVER, 'Editor přiřazené částky', 'Párování', 'Potvrdit/zrušit/rozdělit', ('valid', 'invalid', 'conflict')),
    ComponentId.MATCH_CANDIDATE_PANEL: ComponentSpec(ComponentId.MATCH_CANDIDATE_PANEL, 'Návrh párování', 'Párování', 'Potvrdit/odmítnout/porovnat', ('ready', 'accepted', 'rejected')),
    ComponentId.MATCH_SCORE_DETAIL: ComponentSpec(ComponentId.MATCH_SCORE_DETAIL, 'Vysvětlení jistoty', 'Párování', 'Zobrazit důkazy', ('collapsed', 'open')),
    ComponentId.MATCH_MANUAL_SETTLEMENT: ComponentSpec(ComponentId.MATCH_MANUAL_SETTLEMENT, 'Ruční doplnění', 'Párování', 'Hotovost/jiný zdroj/resolve', ('valid', 'invalid')),
    ComponentId.MATCH_UNDO: ComponentSpec(ComponentId.MATCH_UNDO, 'Vrátit poslední změnu', 'Párování', 'Undo', ('enabled', 'disabled', 'reason')),
    ComponentId.MATCH_REDO: ComponentSpec(ComponentId.MATCH_REDO, 'Znovu provést', 'Párování', 'Redo', ('enabled', 'disabled', 'reason')),
    ComponentId.MATCH_DETAIL_DRAWER: ComponentSpec(ComponentId.MATCH_DETAIL_DRAWER, 'Detail a historie', 'Párování', 'Vazby, zdroj, audit, kopírování', ('closed', 'open', 'loading', 'error')),
    ComponentId.SEARCH_INPUT: ComponentSpec(ComponentId.SEARCH_INPUT, 'Vyhledat doklad, rezervaci nebo platbu', 'Vyhledávání', 'Hledat', ('empty', 'typing', 'results', 'error')),
    ComponentId.SEARCH_FILTERS: ComponentSpec(ComponentId.SEARCH_FILTERS, 'Filtry vyhledávání', 'Vyhledávání', 'Omezit výsledky', ('clean', 'filtered')),
    ComponentId.SEARCH_RESULTS: ComponentSpec(ComponentId.SEARCH_RESULTS, 'Výsledky', 'Vyhledávání', 'Objektové akce a multiselect', ('loading', 'ready', 'empty', 'error')),
    ComponentId.SEARCH_RELATIONS: ComponentSpec(ComponentId.SEARCH_RELATIONS, 'Související položky', 'Vyhledávání', 'Obousměrná navigace', ('loading', 'ready', 'empty')),
    ComponentId.IMPORT_API_CARD: ComponentSpec(ComponentId.IMPORT_API_CARD, 'Better Hotel', 'Importy', 'Stáhnout, test, detail běhu', ('ready', 'running', 'error')),
    ComponentId.IMPORT_BOOKING_DROP: ComponentSpec(ComponentId.IMPORT_BOOKING_DROP, 'Importovat Booking.com CSV', 'Importy', 'Výběr/drop souborů', ('empty', 'validating', 'queued', 'error')),
    ComponentId.IMPORT_BANK_DROP: ComponentSpec(ComponentId.IMPORT_BANK_DROP, 'Importovat bankovní soubor', 'Importy', 'Výběr/drop CSV/XLS/XLSX', ('empty', 'validating', 'queued', 'error')),
    ComponentId.IMPORT_QUEUE: ComponentSpec(ComponentId.IMPORT_QUEUE, 'Fronta souborů', 'Importy', 'Odebrat/spustit', ('empty', 'queued', 'running')),
    ComponentId.IMPORT_RUNS: ComponentSpec(ComponentId.IMPORT_RUNS, 'Historie běhů', 'Importy', 'Detail/retry/objekty', ('loading', 'ready', 'empty')),
    ComponentId.IMPORT_RUN_DETAIL: ComponentSpec(ComponentId.IMPORT_RUN_DETAIL, 'Detail běhu', 'Importy', 'Počty, součty, chyby', ('loading', 'ready', 'error')),
    ComponentId.IMPORT_QUARANTINE: ComponentSpec(ComponentId.IMPORT_QUARANTINE, 'Karanténa', 'Importy', 'Vyřešit, mapovat, ignorovat', ('empty', 'ready', 'error')),
    ComponentId.IMPORT_TYPE_MAPPING: ComponentSpec(ComponentId.IMPORT_TYPE_MAPPING, 'Význam neznámé hodnoty', 'Importy', 'Uložit mapování a znovu zpracovat', ('valid', 'invalid')),
    ComponentId.REPORT_SELECTOR: ComponentSpec(ComponentId.REPORT_SELECTOR, 'Typ sestavy', 'Sestavy', 'Zvolit sestavu', ('ready',)),
    ComponentId.REPORT_FILTERS: ComponentSpec(ComponentId.REPORT_FILTERS, 'Filtry sestavy', 'Sestavy', 'Filtrovat/uložit filtr', ('clean', 'filtered')),
    ComponentId.REPORT_TABLE: ComponentSpec(ComponentId.REPORT_TABLE, 'Živá sestava', 'Sestavy', 'Objektové akce, třídění', ('loading', 'ready', 'empty', 'error')),
    ComponentId.REPORT_EXPORT: ComponentSpec(ComponentId.REPORT_EXPORT, 'Exportovat', 'Sestavy', 'CSV/XLSX/PDF', ('ready', 'running', 'error')),
    ComponentId.AUDIT_FILTERS: ComponentSpec(ComponentId.AUDIT_FILTERS, 'Filtry auditu', 'Audit', 'Filtrovat události', ('clean', 'filtered')),
    ComponentId.AUDIT_TIMELINE: ComponentSpec(ComponentId.AUDIT_TIMELINE, 'Časová osa změn', 'Audit', 'Vybrat událost', ('loading', 'ready', 'empty', 'error')),
    ComponentId.AUDIT_BEFORE_AFTER: ComponentSpec(ComponentId.AUDIT_BEFORE_AFTER, 'Před a po', 'Audit', 'Porovnat stav', ('ready', 'empty')),
    ComponentId.AUDIT_OPEN_CURRENT: ComponentSpec(ComponentId.AUDIT_OPEN_CURRENT, 'Otevřít aktuální stav', 'Audit', 'Navigace na živý objekt', ('enabled', 'disabled')),
    ComponentId.AUDIT_UNDO: ComponentSpec(ComponentId.AUDIT_UNDO, 'Vrátit tuto změnu', 'Audit', 'Kompenzační command', ('enabled', 'disabled', 'reason')),
    ComponentId.SET_API: ComponentSpec(ComponentId.SET_API, 'Připojení Better Hotel', 'Nastavení', 'Tokeny/test', ('untested', 'testing', 'valid', 'error')),
    ComponentId.SET_SYNC: ComponentSpec(ComponentId.SET_SYNC, 'Synchronizace', 'Nastavení', 'Období/blok/overlap/retry', ('clean', 'dirty', 'invalid')),
    ComponentId.SET_MATCH: ComponentSpec(ComponentId.SET_MATCH, 'Pravidla párování', 'Nastavení', 'Tolerance/skóre/kombinace', ('clean', 'dirty', 'invalid')),
    ComponentId.SET_IMPORT: ComponentSpec(ComponentId.SET_IMPORT, 'Importní pravidla', 'Nastavení', 'Složky/status/type mapping', ('clean', 'dirty', 'invalid')),
    ComponentId.SET_DATA: ComponentSpec(ComponentId.SET_DATA, 'Data a zálohy', 'Nastavení', 'Složky/retence/backup/restore', ('clean', 'dirty', 'running', 'error')),
    ComponentId.SET_UI: ComponentSpec(ComponentId.SET_UI, 'Rozhraní', 'Nastavení', 'Layout/sloupce/text', ('clean', 'dirty')),
    ComponentId.GLOBAL_OBJECT_MENU: ComponentSpec(ComponentId.GLOBAL_OBJECT_MENU, 'Další akce', 'Globální', 'ObjectActionRegistry', ('enabled', 'disabled', 'reason')),
    ComponentId.GLOBAL_TOOLTIP: ComponentSpec(ComponentId.GLOBAL_TOOLTIP, 'Kontextová nápověda', 'Globální', 'Hover/focus vysvětlení', ('hidden', 'visible')),
    ComponentId.GLOBAL_TOAST: ComponentSpec(ComponentId.GLOBAL_TOAST, 'Oznámení', 'Globální', 'Výsledek a Undo', ('info', 'success', 'warning', 'error')),
    ComponentId.GLOBAL_ERROR_DIALOG: ComponentSpec(ComponentId.GLOBAL_ERROR_DIALOG, 'Chyba', 'Globální', 'Náprava/retry/detail', ('blocking', 'nonblocking')),
    ComponentId.GLOBAL_PROGRESS: ComponentSpec(ComponentId.GLOBAL_PROGRESS, 'Průběh operace', 'Globální', 'Minimalizovat/zrušit', ('running', 'cancelling', 'completed', 'failed')),
    ComponentId.MATCH_COUNTERPARTS_PANEL: ComponentSpec(ComponentId.MATCH_COUNTERPARTS_PANEL, 'Možné protějšky', 'Párování / detail', 'Seřadit kandidáty, vysvětlit důvody, přidat do výběru', ('loading', 'ready', 'empty', 'expanded-window')),
    ComponentId.MATCH_DATE_WINDOW_CONTROL: ComponentSpec(ComponentId.MATCH_DATE_WINDOW_CONTROL, 'Rozsah hledání', 'Párování', '7 dní / 14 dní / 30 dní / celé období', ('default', 'expanded', 'all-history')),
    ComponentId.MATCH_AGGREGATE_RECONCILIATION: ComponentSpec(ComponentId.MATCH_AGGREGATE_RECONCILIATION, 'Skupinové vyrovnání', 'Párování', 'Vyrovnat jako celek bez falešného rozpisu', ('preview', 'balanced', 'confirmed', 'reopened')),
    ComponentId.MATCH_REVIEW_BANNER: ComponentSpec(ComponentId.MATCH_REVIEW_BANNER, 'Změna zdrojových dat', 'Párování / detail', 'Ukázat změny, znovu ověřit, ponechat rozhodnutí', ('hidden', 'review-required', 'resolved')),
    ComponentId.SETTINGS_VALIDATION_SUMMARY: ComponentSpec(ComponentId.SETTINGS_VALIDATION_SUMMARY, 'Kontrola nastavení', 'Nastavení', 'Souhrn chybných hodnot a přechod na pole', ('hidden', 'invalid', 'valid')),
}


def bind_component(widget: Any, component_id: ComponentId, *, accessible_description: str | None = None) -> Any:
    """Bind a live Qt object to one stable SSOT component identifier."""
    spec = COMPONENT_SPECS[component_id]
    if hasattr(widget, "setObjectName"):
        widget.setObjectName(component_id.value)
    if hasattr(widget, "setAccessibleName"):
        widget.setAccessibleName(spec.human_name)
    if hasattr(widget, "setAccessibleDescription"):
        widget.setAccessibleDescription(accessible_description or spec.primary_function)
    if hasattr(widget, "setProperty"):
        widget.setProperty("ssotComponentId", component_id.value)
        widget.setProperty("ssotStates", "/".join(spec.states))
    return widget


def declared_component_ids() -> frozenset[str]:
    return frozenset(component.value for component in COMPONENT_SPECS)


def assert_registry_complete() -> None:
    if len(COMPONENT_SPECS) != 76:
        raise RuntimeError(f"SSOT component registry must contain 76 entries, found {len(COMPONENT_SPECS)}.")
    if set(COMPONENT_SPECS) != set(ComponentId):
        raise RuntimeError("SSOT component registry and ComponentId are inconsistent.")
