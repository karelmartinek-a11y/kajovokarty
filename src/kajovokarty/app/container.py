from __future__ import annotations

import logging
from dataclasses import dataclass

from ..application.audit import AuditService
from ..application.backup import BackupService
from ..application.counterparts import CounterpartSearchService
from ..application.data_location import DataLocationService
from ..application.import_preflight import ImportPreflightService
from ..application.operations import OperationManager
from ..application.pairing import ManualAllocationService, PairingDropValidationService
from ..application.payment_reconciliation import DocumentPaymentService
from ..application.quarantine import QuarantineService
from ..application.reconciliation import ReconciliationService
from ..application.reference_resolution import BookingReferenceResolutionService
from ..application.reporting import ReportingService
from ..application.saved_filters import SavedFilterService
from ..application.search import SearchService
from ..application.settings import SettingsService
from ..application.view_state import ViewStateService
from ..domain.reference_parser import ReservationReferenceParser
from ..infrastructure.better_hotel.sync import BetterHotelSyncService
from ..infrastructure.diagnostics.bundle import DiagnosticBundleService
from ..infrastructure.diagnostics.logging import configure_logging
from ..infrastructure.importers.bank_file import BankFileImportService
from ..infrastructure.importers.booking_csv import BookingCsvImportService
from ..infrastructure.persistence.database import Database
from ..infrastructure.security.secrets import SecretStore
from .paths import AppPaths


@dataclass(slots=True)
class ServiceContainer:
    paths: AppPaths
    database: Database
    logger: logging.Logger
    audit: AuditService
    settings: SettingsService
    view_state: ViewStateService
    secrets: SecretStore
    booking_import: BookingCsvImportService
    bank_import: BankFileImportService
    import_preflight: ImportPreflightService
    quarantine: QuarantineService
    better_hotel_sync: BetterHotelSyncService
    pairing: ManualAllocationService
    payments: DocumentPaymentService
    drop_validation: PairingDropValidationService
    counterparts: CounterpartSearchService
    reconciliation: ReconciliationService
    reference_resolution: BookingReferenceResolutionService
    search: SearchService
    reporting: ReportingService
    saved_filters: SavedFilterService
    backup: BackupService
    data_location: DataLocationService
    diagnostics: DiagnosticBundleService
    operations: OperationManager

    @classmethod
    def build(cls, paths: AppPaths | None = None) -> ServiceContainer:
        app_paths = paths or AppPaths.discover()
        app_paths.ensure()
        database = Database(app_paths.database, app_paths.migrations, app_paths.backups)
        database.migrate()
        database.mark_startup()
        logger = configure_logging(app_paths.logs)
        audit = AuditService()
        settings = SettingsService(database, audit)
        secrets = SecretStore(app_paths)
        pairing = ManualAllocationService(database, audit)
        search = SearchService(database)
        booking_import = BookingCsvImportService(database)
        bank_import = BankFileImportService(database)
        backup = BackupService(database, app_paths, audit, settings)
        container = cls(
            paths=app_paths,
            database=database,
            logger=logger,
            audit=audit,
            settings=settings,
            view_state=ViewStateService(database),
            secrets=secrets,
            booking_import=booking_import,
            bank_import=bank_import,
            import_preflight=ImportPreflightService(database, booking_import, bank_import),
            quarantine=QuarantineService(database, audit, booking_import, bank_import),
            better_hotel_sync=BetterHotelSyncService(database, ReservationReferenceParser()),
            pairing=pairing,
            payments=DocumentPaymentService(database, pairing, audit),
            drop_validation=PairingDropValidationService(database),
            counterparts=CounterpartSearchService(database),
            reconciliation=ReconciliationService(database, pairing),
            reference_resolution=BookingReferenceResolutionService(database, audit),
            search=search,
            reporting=ReportingService(database),
            saved_filters=SavedFilterService(database, audit),
            backup=backup,
            data_location=DataLocationService(app_paths, database, audit, backup),
            diagnostics=DiagnosticBundleService(app_paths, database),
            operations=OperationManager(database),
        )
        search.rebuild_index()
        return container

    def close(self) -> None:
        self.operations.shutdown(cancel=True)
        self.database.mark_clean_shutdown()
        for handler in tuple(self.logger.handlers):
            handler.close()
