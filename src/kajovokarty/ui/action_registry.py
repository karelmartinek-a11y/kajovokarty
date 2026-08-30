from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMenu, QWidget

from .component_registry import ComponentId, bind_component


class ActionId(StrEnum):
    OPEN_DETAIL = "OPEN_DETAIL"
    OPEN_IN_MATCHING = "OPEN_IN_MATCHING"
    ADD_TO_TRAY = "ADD_TO_TRAY"
    PAIR_SELECTED = "PAIR_SELECTED"
    CREATE_GROUP = "CREATE_GROUP"
    SPLIT_SOURCE = "SPLIT_SOURCE"
    SPLIT_DOCUMENT = "SPLIT_DOCUMENT"
    EDIT_ALLOCATION = "EDIT_ALLOCATION"
    REMOVE_ALLOCATION = "REMOVE_ALLOCATION"
    REMOVE_GROUP = "REMOVE_GROUP"
    ACCEPT_CANDIDATE = "ACCEPT_CANDIDATE"
    REJECT_CANDIDATE = "REJECT_CANDIDATE"
    MARK_CASH = "MARK_CASH"
    MARK_OTHER = "MARK_OTHER"
    MANUAL_RESOLVE = "MANUAL_RESOLVE"
    MARK_DOCUMENT_PAID = "MARK_DOCUMENT_PAID"
    CLEAR_DOCUMENT_MANUAL_PAID = "CLEAR_DOCUMENT_MANUAL_PAID"
    INCLUDE = "INCLUDE"
    EXCLUDE = "EXCLUDE"
    SHOW_RELATIONS = "SHOW_RELATIONS"
    SHOW_AUDIT = "SHOW_AUDIT"
    SHOW_SOURCE_ROW = "SHOW_SOURCE_ROW"
    COPY_PRIMARY_ID = "COPY_PRIMARY_ID"
    COPY_ALL_IDS = "COPY_ALL_IDS"
    EXPORT_SELECTION = "EXPORT_SELECTION"
    UNDO = "UNDO"
    REDO = "REDO"
    RETRY_RUN = "RETRY_RUN"
    OPEN_QUARANTINE = "OPEN_QUARANTINE"
    RESOLVE_QUARANTINE = "RESOLVE_QUARANTINE"
    REFRESH_OBJECT = "REFRESH_OBJECT"
    FIND_COUNTERPARTS = "FIND_COUNTERPARTS"
    EXPAND_SEARCH_WINDOW = "EXPAND_SEARCH_WINDOW"
    BALANCE_AS_GROUP = "BALANCE_AS_GROUP"
    REVALIDATE_GROUP = "REVALIDATE_GROUP"
    EDIT_MANUAL_SETTLEMENT = "EDIT_MANUAL_SETTLEMENT"
    REMOVE_MANUAL_SETTLEMENT = "REMOVE_MANUAL_SETTLEMENT"
    REOPEN_MANUAL_RESOLUTION = "REOPEN_MANUAL_RESOLUTION"
    REMOVE_FROM_TRAY = "REMOVE_FROM_TRAY"
    CLEAR_TRAY = "CLEAR_TRAY"


@dataclass(frozen=True, slots=True)
class ObjectContext:
    object_type: str
    object_id: str
    primary_label: str
    currency: str | None = None
    amount_minor: int | None = None
    row_version: int | None = None
    status: str | None = None
    view: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    @property
    def object_ref(self) -> str:
        return f"{self.object_type}:{self.object_id}"


@dataclass(frozen=True, slots=True)
class ActionSpec:
    action_id: ActionId
    group: str
    text: str
    tooltip: str
    shortcut: str | None
    object_types: frozenset[str]
    audit_event: str


Handler = Callable[[ActionId, list[ObjectContext]], None]
LabelProvider = Callable[[ActionId, str], str]


_SPECS = (
    ActionSpec(ActionId.OPEN_DETAIL, "Otevřít", "Otevřít detail", "Zobrazí všechny dostupné údaje, původ, vazby a historii této položky.", "Enter", frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "ALLOCATION", "RESERVATION", "IMPORT_RUN", "QUARANTINE", "CANDIDATE", "MANUAL", "AUDIT", "BOOKING_REFERENCE", "BILL", "BILL_ITEM", "REVISION_ALERT"}), "OBJECT_DETAIL_OPENED"),
    ActionSpec(ActionId.OPEN_IN_MATCHING, "Otevřít", "Otevřít v párování", "Přejde na párovací plochu, vybere tuto položku a zobrazí možné protějšky.", "Ctrl+Enter", frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "RESERVATION", "MANUAL"}), "OBJECT_OPENED_IN_MATCHING"),
    ActionSpec(ActionId.SHOW_RELATIONS, "Otevřít", "Zobrazit související položky", "Ukáže rezervace, faktury, zdroje úhrad a skupiny navázané na tuto položku.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "RESERVATION", "MANUAL", "BILL", "BILL_ITEM", "BOOKING_REFERENCE", "REVISION_ALERT", "CANDIDATE", "IMPORT_RUN", "AUDIT"}), "RELATIONS_OPENED"),
    ActionSpec(ActionId.ADD_TO_TRAY, "Párování", "Přidat do pracovního výběru", "Ponechá položku ve spodní liště, abyste k ní mohli přidat další doklady nebo platby z jiného pohledu.", "Ctrl+Space", frozenset({"INVOICE", "BOOKING", "CARD", "MANUAL"}), "TRAY_ITEM_ADDED"),
    ActionSpec(ActionId.PAIR_SELECTED, "Párování", "Spárovat vybrané", "Otevře náhled společného párování vybraných dokladů a zdrojů.", "Ctrl+M", frozenset({"INVOICE", "BOOKING", "CARD", "MANUAL"}), "PAIR_SELECTED"),
    ActionSpec(ActionId.CREATE_GROUP, "Párování", "Vytvořit vyrovnávací skupinu", "Vytvoří pracovní skupinu z vybraných položek a před uložením ukáže součty a rozdíl.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MANUAL"}), "GROUP_CREATED"),
    ActionSpec(ActionId.SPLIT_SOURCE, "Párování", "Rozdělit platbu", "Rozdělí zbývající částku této platby mezi více dokladů.", "F2", frozenset({"BOOKING", "CARD", "MANUAL"}), "SOURCE_SPLIT"),
    ActionSpec(ActionId.SPLIT_DOCUMENT, "Párování", "Rozdělit doklad", "Umožní pokrýt tento doklad několika zdroji úhrad.", "F2", frozenset({"INVOICE"}), "DOCUMENT_SPLIT"),
    ActionSpec(ActionId.EDIT_ALLOCATION, "Párování", "Upravit přiřazenou částku", "Změní částku této konkrétní vazby a ukáže nové zůstatky.", "F2", frozenset({"ALLOCATION"}), "ALLOCATION_EDITED"),
    ActionSpec(ActionId.REMOVE_ALLOCATION, "Zrušení", "Rozpojit tuto vazbu", "Odebere pouze vybrané spojení. Zdrojová data zůstanou beze změny a akci lze vrátit.", "Delete", frozenset({"ALLOCATION"}), "ALLOCATION_REMOVED"),
    ActionSpec(ActionId.REMOVE_GROUP, "Zrušení", "Rozpojit celou skupinu", "Odebere všechny aktivní vazby ve skupině po zobrazení dopadu.", "Shift+Delete", frozenset({"MATCH_GROUP"}), "GROUP_REMOVED"),
    ActionSpec(ActionId.ACCEPT_CANDIDATE, "Párování", "Potvrdit návrh", "Převede navržené spojení na ručně potvrzené párování.", "Ctrl+Enter", frozenset({"CANDIDATE", "BOOKING_REFERENCE"}), "CANDIDATE_ACCEPTED"),
    ActionSpec(ActionId.REJECT_CANDIDATE, "Párování", "Odmítnout návrh", "Tento návrh se nebude znovu nabízet, dokud se nezmění data nebo pravidla.", None, frozenset({"CANDIDATE", "BOOKING_REFERENCE"}), "CANDIDATE_REJECTED"),
    ActionSpec(ActionId.MARK_CASH, "Vyřešení", "Doplnit jako hotovost", "Předvyplní zbývající částku a uloží ji jako ručně potvrzenou hotovost.", None, frozenset({"INVOICE", "MATCH_GROUP"}), "CASH_ADDED"),
    ActionSpec(ActionId.MARK_OTHER, "Vyřešení", "Doplnit jiným zdrojem", "Předvyplní zbývající částku a umožní pojmenovat jiný ruční zdroj.", None, frozenset({"INVOICE", "MATCH_GROUP"}), "OTHER_SOURCE_ADDED"),
    ActionSpec(ActionId.MANUAL_RESOLVE, "Vyřešení", "Označit jako ručně vyřešené", "Uzavře rozdíl bez vytváření fiktivní externí platby. Rozhodnutí bude viditelně označené a auditované.", None, frozenset({"INVOICE", "MATCH_GROUP"}), "MANUAL_RESOLVED"),
    ActionSpec(ActionId.MARK_DOCUMENT_PAID, "Vyřešení", "Označit doklad jako uhrazený bez důkazu", "Označí tento doklad jako uhrazený ručním rozhodnutím bez spotřebování externího potvrzení.", None, frozenset({"INVOICE"}), "DOCUMENT_MANUALLY_PAID"),
    ActionSpec(ActionId.CLEAR_DOCUMENT_MANUAL_PAID, "Zrušení", "Zrušit ruční úhradu dokladu", "Zruší ruční označení a vrátí doklad do výpočtu podle skutečných potvrzení.", None, frozenset({"INVOICE"}), "DOCUMENT_MANUAL_PAYMENT_CLEARED"),
    ActionSpec(ActionId.INCLUDE, "Kontrola", "Zahrnout do kontroly", "Přidá doklad do kontrolované množiny bez změny dat v Better Hotelu.", None, frozenset({"INVOICE"}), "INVOICE_INCLUDED"),
    ActionSpec(ActionId.EXCLUDE, "Kontrola", "Vyřadit z kontroly", "Přestane doklad zahrnovat do rozdílů. Zdrojový doklad se nesmaže.", None, frozenset({"INVOICE"}), "INVOICE_EXCLUDED"),
    ActionSpec(ActionId.SHOW_AUDIT, "Kontrola", "Zobrazit historii změn", "Otevře časovou osu všech importů, automatických návrhů a ručních zásahů.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "ALLOCATION", "RESERVATION", "IMPORT_RUN", "QUARANTINE", "CANDIDATE", "MANUAL", "AUDIT", "BOOKING_REFERENCE", "BILL", "BILL_ITEM", "REVISION_ALERT"}), "AUDIT_OPENED"),
    ActionSpec(ActionId.SHOW_SOURCE_ROW, "Kontrola", "Zobrazit původní zdrojový řádek", "Ukáže kanonizovaný řádek nebo API snapshot, ze kterého tato položka vznikla.", None, frozenset({"INVOICE", "BOOKING", "CARD", "RESERVATION", "QUARANTINE", "BOOKING_REFERENCE", "BILL", "BILL_ITEM"}), "SOURCE_ROW_OPENED"),
    ActionSpec(ActionId.COPY_PRIMARY_ID, "Nástroje", "Kopírovat hlavní identifikátor", "Zkopíruje číslo dokladu, Booking.com číslo nebo SEQ ID podle typu položky.", "Ctrl+C", frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "ALLOCATION", "RESERVATION", "IMPORT_RUN", "QUARANTINE", "CANDIDATE", "MANUAL", "AUDIT", "BOOKING_REFERENCE", "BILL", "BILL_ITEM", "REVISION_ALERT"}), "PRIMARY_ID_COPIED"),
    ActionSpec(ActionId.COPY_ALL_IDS, "Nástroje", "Kopírovat všechny identifikátory", "Zkopíruje přehled všech dostupných technických identifikátorů.", "Ctrl+Shift+C", frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "ALLOCATION", "RESERVATION", "IMPORT_RUN", "QUARANTINE", "CANDIDATE", "MANUAL", "AUDIT", "BOOKING_REFERENCE", "BILL", "BILL_ITEM", "REVISION_ALERT"}), "ALL_IDS_COPIED"),
    ActionSpec(ActionId.EXPORT_SELECTION, "Nástroje", "Exportovat vybrané", "Vytvoří export pouze z vybraných položek se zachováním měny a aktivních filtrů.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP", "RESERVATION", "IMPORT_RUN", "QUARANTINE", "CANDIDATE", "MANUAL", "AUDIT", "BOOKING_REFERENCE", "BILL", "BILL_ITEM", "REVISION_ALERT"}), "SELECTION_EXPORTED"),
    ActionSpec(ActionId.UNDO, "Zrušení", "Vrátit: <poslední akce>", "Provede bezpečný kompenzační příkaz a zachová auditní historii.", "Ctrl+Z", frozenset({"GLOBAL", "AUDIT"}), "COMMAND_UNDO"),
    ActionSpec(ActionId.REDO, "Zrušení", "Znovu: <vrácená akce>", "Znovu provede naposledy vrácenou akci, pokud je stále bezpečná.", "Ctrl+Y", frozenset({"GLOBAL"}), "COMMAND_REDO"),
    ActionSpec(ActionId.RETRY_RUN, "Nástroje", "Zopakovat běh", "Znovu spustí stejný import nebo synchronizační rozsah s aktuálním nastavením.", None, frozenset({"IMPORT_RUN"}), "RUN_RETRIED"),
    ActionSpec(ActionId.OPEN_QUARANTINE, "Nástroje", "Otevřít karanténu", "Zobrazí řádky, které nebylo možné bezpečně importovat.", None, frozenset({"IMPORT_RUN"}), "QUARANTINE_OPENED"),
    ActionSpec(ActionId.RESOLVE_QUARANTINE, "Nástroje", "Vyřešit řádek", "Umožní zvolit význam neznámé hodnoty nebo řádek vědomě ignorovat a znovu zpracovat.", None, frozenset({"QUARANTINE"}), "QUARANTINE_RESOLVED"),
    ActionSpec(ActionId.REFRESH_OBJECT, "Nástroje", "Načíst aktuální stav z API", "Provede jeden bezpečný GET a aktualizuje tento objekt bez změny Better Hotelu.", None, frozenset({"INVOICE", "RESERVATION", "BOOKING_REFERENCE", "BILL", "BILL_ITEM"}), "OBJECT_REFRESHED"),
    ActionSpec(ActionId.FIND_COUNTERPARTS, "Párování", "Najít možné protějšky", "Vyhledá možné doklady nebo zdroje podle měny, částky, reference a data a vysvětlí pořadí výsledků.", "Ctrl+Shift+F", frozenset({"INVOICE", "BOOKING", "CARD", "MANUAL"}), "COUNTERPARTS_FOUND"),
    ActionSpec(ActionId.EXPAND_SEARCH_WINDOW, "Párování", "Rozšířit hledání v čase", "Rozšíří hledání na 14 dní, 30 dní nebo celé období. Vzdálené výsledky zůstanou návrhy k potvrzení.", None, frozenset({"INVOICE", "BOOKING", "CARD", "CANDIDATE"}), "SEARCH_WINDOW_EXPANDED"),
    ActionSpec(ActionId.BALANCE_AS_GROUP, "Párování", "Vyrovnat skupinu jako celek", "Potvrdí souhrnnou rovnost vybraných dokladů a zdrojů bez vytvoření neprokázaných vazeb mezi jednotlivými položkami.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MATCH_GROUP"}), "GROUP_AGGREGATE_BALANCED"),
    ActionSpec(ActionId.REVALIDATE_GROUP, "Kontrola", "Znovu ověřit skupinu", "Přepočítá skupinu z aktuálních zdrojových dat a ukáže všechny změny před potvrzením.", None, frozenset({"MATCH_GROUP", "REVISION_ALERT"}), "GROUP_REVALIDATED"),
    ActionSpec(ActionId.EDIT_MANUAL_SETTLEMENT, "Párování", "Upravit ruční zdroj", "Změní částku, typ nebo popis ruční hotovosti či jiného zdroje a okamžitě přepočítá rozdíl.", "F2", frozenset({"MANUAL"}), "MANUAL_SETTLEMENT_EDITED"),
    ActionSpec(ActionId.REMOVE_MANUAL_SETTLEMENT, "Zrušení", "Odebrat ruční zdroj", "Vrátí ruční hotovost nebo jiný zdroj, zachová audit a nabídne možnost změnu vrátit.", "Delete", frozenset({"MANUAL"}), "MANUAL_SETTLEMENT_REMOVED"),
    ActionSpec(ActionId.REOPEN_MANUAL_RESOLUTION, "Vyřešení", "Znovu otevřít ruční vyřešení", "Vrátí případ do pracovního stavu, aby bylo možné upravit nebo doplnit důkazy a vazby.", None, frozenset({"MATCH_GROUP", "REVISION_ALERT"}), "MANUAL_RESOLUTION_REOPENED"),
    ActionSpec(ActionId.REMOVE_FROM_TRAY, "Párování", "Odebrat z pracovního výběru", "Odebere pouze tuto položku ze spodní pracovní lišty; žádné párování se nezmění.", None, frozenset({"INVOICE", "BOOKING", "CARD", "MANUAL"}), "TRAY_ITEM_REMOVED"),
    ActionSpec(ActionId.CLEAR_TRAY, "Párování", "Vyprázdnit pracovní výběr", "Odebere všechny položky z pracovního výběru bez změny zdrojových dat nebo vazeb.", None, frozenset({"GLOBAL"}), "TRAY_CLEARED"),
)


class ObjectActionRegistry:
    def __init__(self, handler: Handler, label_provider: LabelProvider | None = None) -> None:
        self.handler = handler
        self.label_provider = label_provider
        self.specs = {spec.action_id: spec for spec in _SPECS}

    def applicable(self, contexts: Iterable[ObjectContext]) -> list[ActionSpec]:
        items = list(contexts)
        if not items:
            return [self.specs[action_id] for action_id in (ActionId.UNDO, ActionId.REDO, ActionId.CLEAR_TRAY)]
        object_types = {item.object_type for item in items}
        return [spec for spec in _SPECS if object_types <= spec.object_types or (len(items) > 1 and spec.action_id in {ActionId.PAIR_SELECTED, ActionId.CREATE_GROUP, ActionId.BALANCE_AS_GROUP, ActionId.EXPORT_SELECTION})]

    def create_action(self, parent: QWidget, action_id: ActionId, contexts: list[ObjectContext]) -> QAction:
        spec = self.specs[action_id]
        text = self.label_provider(action_id, spec.text) if self.label_provider else spec.text
        action = QAction(text, parent)
        action.setObjectName(f"action_{action_id.value}")
        action.setToolTip(spec.tooltip)
        action.setStatusTip(spec.tooltip)
        action.setData(action_id.value)
        if spec.shortcut:
            action.setShortcut(QKeySequence(spec.shortcut))
            action.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        enabled, reason = self.availability(action_id, contexts)
        action.setEnabled(enabled)
        if not enabled and reason:
            action.setToolTip(f"{spec.tooltip}\n\n{reason}")
            action.setStatusTip(reason)
        action.triggered.connect(lambda checked=False, aid=action_id, ctx=list(contexts): self.handler(aid, ctx))
        return action

    def build_menu(self, parent: QWidget, contexts: list[ObjectContext]) -> QMenu:
        menu = QMenu(parent)
        bind_component(menu, ComponentId.GLOBAL_OBJECT_MENU)
        previous_group = ""
        for spec in self.applicable(contexts):
            if previous_group and previous_group != spec.group:
                menu.addSeparator()
            menu.addAction(self.create_action(menu, spec.action_id, contexts))
            previous_group = spec.group
        return menu

    def availability(self, action_id: ActionId, contexts: list[ObjectContext]) -> tuple[bool, str]:
        if action_id in {ActionId.UNDO, ActionId.REDO, ActionId.CLEAR_TRAY}:
            return True, ""
        if not contexts:
            return False, "Vyberte položku."
        if action_id in {ActionId.PAIR_SELECTED, ActionId.CREATE_GROUP, ActionId.BALANCE_AS_GROUP}:
            sides = {"DOCUMENT" if item.object_type == "INVOICE" else "SOURCE" for item in contexts if item.object_type in {"INVOICE", "BOOKING", "CARD", "MANUAL"}}
            if sides != {"DOCUMENT", "SOURCE"}:
                return False, "Vyberte alespoň jeden doklad a jeden zdroj úhrady."
            currencies = {item.currency for item in contexts if item.currency}
            if len(currencies) > 1:
                return False, "Nelze spojit: výběr obsahuje více měn."
            if action_id == ActionId.BALANCE_AS_GROUP:
                doc_total = sum(item.amount_minor or 0 for item in contexts if item.object_type == "INVOICE")
                src_total = sum(item.amount_minor or 0 for item in contexts if item.object_type != "INVOICE")
                if doc_total != src_total:
                    return False, "Skupinu lze vyrovnat jako celek pouze při rozdílu 0."
        if any(item.status == "REVIEW_REQUIRED" for item in contexts) and action_id not in {ActionId.REVALIDATE_GROUP, ActionId.SHOW_AUDIT, ActionId.OPEN_DETAIL, ActionId.REOPEN_MANUAL_RESOLUTION}:
            return False, "Tento případ vyžaduje kontrolu. Zvolte Znovu ověřit skupinu."
        if action_id == ActionId.INCLUDE and any(item.data.get("included", True) for item in contexts):
            return False, "Doklad už je zahrnutý v kontrolované množině."
        if action_id == ActionId.EXCLUDE and any(not item.data.get("included", True) for item in contexts):
            return False, "Doklad už je vyřazený z kontrolované množiny."
        return True, ""

    def conformance_snapshot(self) -> list[dict[str, Any]]:
        return [
            {
                "id": spec.action_id.value,
                "group": spec.group,
                "text": spec.text,
                "tooltip": spec.tooltip,
                "shortcut": spec.shortcut,
                "object_types": sorted(spec.object_types),
                "audit_event": spec.audit_event,
            }
            for spec in _SPECS
        ]
