from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

BETTER_HOTEL_BASE_URL = "https://api.better-hotel.com/api/connector/v/1"
PYTHON_PATCH_VERSION = "3.11.9"
APP_VERSION = "1.1.0"


def default_sync_start() -> date:
    """Start with one year of history; do not let the default age over time."""
    return date.today() - timedelta(days=365)


@dataclass(frozen=True, slots=True)
class AppDefaults:
    first_controlled_day: date = field(default_factory=default_sync_start)
    history_block_days: int = 7
    modified_overlap_hours: int = 48
    request_timeout_seconds: int = 30
    retry_count: int = 3
    requests_per_second: float = 2.0
    tolerance_minor: int = 1
    auto_match_threshold: int = 95
    score_margin: int = 15
    max_combination: int = 6
    warning_age_days: int = 30
    log_retention_days: int = 30
    snapshot_retention_days: int = 365
    max_import_megabytes: int = 100
    auto_match_after_import: bool = True


@dataclass(frozen=True, slots=True)
class SettingSpec:
    key: str
    group: str
    label: str
    tooltip: str
    default: Any
    minimum: int | float | None = None
    maximum: int | float | None = None
    choices: tuple[Any, ...] = ()


DEFAULTS = AppDefaults()


def _spec(key: str, group: str, label: str, tooltip: str, default: Any, minimum: int | float | None = None, maximum: int | float | None = None, choices: tuple[Any, ...] = ()) -> SettingSpec:
    return SettingSpec(key, group, label, tooltip, default, minimum, maximum, choices)


SETTING_SPECS: dict[str, SettingSpec] = {
    spec.key: spec
    for spec in (
        _spec("sync.first_controlled_day", "Synchronizace", "První kontrolovaný den", "Určuje nejstarší datum, které se při stažení z Better Hotelu zkontroluje. Starší údaje se nestahují. Výchozí nastavení pokrývá poslední rok.", DEFAULTS.first_controlled_day),
        _spec("sync.history_block_days", "Synchronizace", "Délka historického bloku", "Synchronizace zpracovává historii po částech. Menší počet dní znamená častější ukládání a snadnější zrušení, větší počet může být rychlejší. Doporučení: 7 dní.", 7, 1, 31),
        _spec("sync.modified_overlap_hours", "Synchronizace", "Překontrolovat změny za poslední", "Při každém dalším stažení se znovu prověří i údaje změněné v tomto počtu hodin. Chrání před tím, aby pozdě upravená rezervace nebo faktura zůstala přehlédnuta. Doporučení: 48 hodin.", 48, 0, 168),
        _spec("sync.timeout_seconds", "Synchronizace", "Čekat na odpověď nejvýše", "Jak dlouho program čeká na odpověď Better Hotelu u jednoho dotazu. Při pomalém internetu pomůže vyšší hodnota, při výpadku pak program déle čeká. Doporučení: 30 sekund.", 30, 5, 120),
        _spec("sync.retry_count", "Synchronizace", "Opakovat neúspěšný dotaz", "Kolikrát program zkusí znovu dočasně neúspěšné stažení. Vyšší hodnota lépe zvládne krátký výpadek, ale synchronizace může trvat déle. Doporučení: 3 opakování.", 3, 0, 5),
        _spec("sync.requests_per_second", "Synchronizace", "Rychlost stahování", "Omezuje počet dotazů odeslaných za sekundu do Better Hotelu. Vyšší hodnota bývá rychlejší, ale může narazit na limit služby. Doporučení: nejvyšší bezpečná hodnota 2 dotazy za sekundu.", 2.0, 0.2, 2.0),
        _spec("matching.tolerance_minor", "Párování", "Povolený rozdíl částky", "Určuje, o kolik haléřů (Kč) nebo centů (EUR) se mohou lišit částky dokladu a platby, aby je program ještě považoval za stejné. Měna se nikdy nepřevádí. Doporučení: 1.", 1, 0, 100),
        _spec("matching.band_1_days", "Párování", "Stejné datum přibližně do", "Platba a doklad s rozdílem nejvýše tohoto počtu dní dostanou nejsilnější bodové hodnocení. Doporučení: 2 dny.", 2, 0, 30),
        _spec("matching.band_2_days", "Párování", "Přijatelné datum přibližně do", "Platba a doklad s větším, ale stále přijatelným rozdílem data dostanou střední bodové hodnocení. Musí být nejméně stejně velké jako první pásmo. Doporučení: 4 dny.", 4, 0, 30),
        _spec("matching.band_3_days", "Párování", "Nejzazší datum pro hledání", "Za tímto počtem dní už program datum nepovažuje za dostatečně blízké a kandidáta nenabídne. Vyšší hodnota hledá více možností, ale může přidat omyly. Doporučení: 7 dní.", 7, 0, 30),
        _spec("matching.auto_threshold", "Párování", "Jistota pro automatické spojení", "Nejnižší celkové hodnocení, při kterém může program spojení potvrdit sám. Stále musí souhlasit částka, měna a nejlepší možnost musí být jednoznačná. Doporučení: 95 ze 100.", 95, 90, 100),
        _spec("matching.score_margin", "Párování", "Náskok před druhou možností", "O kolik bodů musí nejlepší možnost předčit druhou nejlepší, aby ji program mohl potvrdit bez dotazu. Vyšší hodnota znamená méně automatických, ale jistější spojení. Doporučení: 15 bodů.", 15, 0, 100),
        _spec("matching.max_combination", "Párování", "Kolik položek hledat dohromady", "Nejvyšší počet dokladů a plateb, které program zkouší spojit do jednoho případu. Vyšší hodnota najde složitější případy, ale výpočet může být výrazně delší. Doporučení: 6 položek.", 6, 2, 10),
        _spec("matching.warning_age_days", "Párování", "Po kolika dnech upozornit", "Nevyřešené rozdíly starší než tento počet dní se v přehledech zvýrazní, aby bylo jasné, že čekají na kontrolu. Doporučení: 30 dní.", 30, 1, 3650),
        _spec("imports.auto_match", "Importy", "Po importu automaticky hledat párování", "Po úspěšném načtení souboru nebo API dat program sám přepočítá návrhy spojení faktur s platbami. Vypněte, pokud chcete párování spouštět ručně.", True),
        _spec("imports.max_megabytes", "Importy", "Největší povolený soubor", "Soubor větší než tato velikost se odmítne ještě před načtením. Vyšší hodnota dovolí načítat větší exporty, ale spotřebuje více paměti. Doporučení: 100 MB.", 100, 1, 2048),
        _spec("imports.multiple_sheets", "Importy", "Když soubor obsahuje více listů", "Určuje, co se stane u Excelu s více listy, které vypadají jako bankovní výpis. Výchozí volba vždy zobrazí dotaz, aby se nenačetl špatný list.", "ask", choices=("ask",)),
        _spec("imports.booking_directory", "Importy", "Složka pro výběr Booking.com", "Složka, kterou program nabídne jako první při tlačítku pro výběr Booking.com CSV. Neurčuje, kam se data uloží.", ""),
        _spec("imports.bank_directory", "Importy", "Složka pro výběr banky", "Složka, kterou program nabídne jako první při tlačítku pro výběr bankovního CSV, XLS nebo XLSX. Neurčuje, kam se data uloží.", ""),
        _spec("data.log_retention_days", "Data", "Jak dlouho uchovat záznamy o činnosti", "Program si ukládá technické záznamy o tom, kdy se spustil import, synchronizace nebo záloha a zda proběhla úspěšně. Zde určíte, po kolika dnech se tyto záznamy smažou. Delší doba zabere více místa.", 30, 1, 3650),
        _spec("data.snapshot_retention_days", "Data", "Jak dlouho uchovat původní podklady", "Při importu si program ukládá kopii původních řádků a odpovědí z Better Hotelu, aby šlo později dohledat, z čeho výsledek vznikl. Zde určíte, po kolika dnech se tyto kopie smažou. Doporučení: 365 dní.", 365, 1, 3650),
        _spec("data.data_directory", "Data", "Kam ukládat data programu", "Složka, ve které program uchovává databázi, nastavení, zašifrované tokeny a technické záznamy. Změna se použije po restartu. Složka musí být pravidelně zálohovaná.", ""),
        _spec("data.export_directory", "Data", "Kam ukládat exportované sestavy", "Složka, kterou program nabídne jako první při ukládání reportu nebo exportu. Samotný export se vytvoří až po vašem potvrzení.", ""),
        _spec("data.backup_directory", "Data", "Kam ukládat zálohy databáze", "Složka pro automatické i ručně vytvořené kopie databáze. Ideální je jiný disk nebo umístění než u hlavních dat.", ""),
        _spec("ui.row_density", "Rozhraní", "Výška řádků v tabulkách", "Mění výšku jednotlivých řádků v tabulkách Importy, Párování, Vyhledávání, Sestavy a Audit. Kompaktní zobrazí více řádků najednou, pohodlné se lépe čte.", "normal", choices=("compact", "normal", "comfortable")),
        _spec("ui.text_scale", "Rozhraní", "Velikost písma", "Zvětší nebo zmenší písmo v celém programu, včetně tabulek, tlačítek a popisků. Nemění velikost oken systému Windows. Doporučená hodnota: 100 %.", 100, 80, 160),
        _spec("ui.high_contrast", "Rozhraní", "Kontrastní vzhled", "Zvýší rozdíl mezi textem, pozadím a ovládacími prvky v celém programu. Pomáhá při horší čitelnosti; informace nejsou sdělovány pouze barvou.", False),
        _spec("ui.reduce_motion", "Rozhraní", "Omezit pohyblivé efekty", "Omezí nepodstatné animace a přechody při práci v programu. Funkce a data zůstanou stejné, změna ovlivní pouze zobrazování.", False),
        _spec("ui.last_view", "Rozhraní", "Poslední pohled", "Interní volba poslední otevřené obrazovky.", "dashboard", choices=("dashboard", "matching", "search", "imports", "reports", "audit", "settings")),
        _spec("backup.daily", "Data", "Vytvářet denní zálohu", "Při prvním spuštění programu v daný den vytvoří kopii databáze. Doporučujeme ponechat zapnuté, protože záloha pomůže po chybě nebo nechtěné změně dat.", True),
        _spec("backup.retention_days", "Data", "Jak dlouho uchovat zálohy", "Určuje, po kolika dnech se staré automatické kopie databáze smažou. Delší doba poskytne více možností návratu, ale zabere více místa.", 30, 1, 3650),
    )
}


def today_utc_date() -> date:
    return date.today()
