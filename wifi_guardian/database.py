from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, create_engine, delete, event, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from .config import CONFIG


class Base(DeclarativeBase):
    pass


class TrafficSample(Base):
    __tablename__ = "traffic_samples"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True
    )
    download_bps: Mapped[float] = mapped_column(Float, default=0)
    upload_bps: Mapped[float] = mapped_column(Float, default=0)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    packet_loss: Mapped[float | None] = mapped_column(Float, nullable=True)


class KnownDevice(Base):
    __tablename__ = "known_devices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ip_address: Mapped[str] = mapped_column(String(45), index=True)
    mac_address: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    hostname: Mapped[str | None] = mapped_column(String(255), nullable=True)
    custom_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    source: Mapped[str] = mapped_column(String(32), default="LAN")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reachable: Mapped[bool] = mapped_column(Boolean, default=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc)
    )
    action: Mapped[str] = mapped_column(String(100))
    target: Mapped[str] = mapped_column(String(255))
    result: Mapped[str] = mapped_column(String(40))
    detail: Mapped[str | None] = mapped_column(String(500), nullable=True)


class Repository:
    def __init__(self, url: str = CONFIG.database_url) -> None:
        connect_args = {"timeout": 5} if url.startswith("sqlite") else {}
        self.engine = create_engine(url, future=True, connect_args=connect_args)
        if url.startswith("sqlite"):
            @event.listens_for(self.engine, "connect")
            def _configure_sqlite(connection, _record) -> None:  # type: ignore[no-untyped-def]
                cursor = connection.cursor()
                cursor.execute("PRAGMA busy_timeout=5000")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.close()
        Base.metadata.create_all(self.engine)

    def add_sample(
        self,
        download_bps: float,
        upload_bps: float,
        latency_ms: float | None,
        packet_loss: float | None,
        created_at: datetime | None = None,
    ) -> None:
        with Session(self.engine) as session:
            session.add(
                TrafficSample(
                    download_bps=download_bps,
                    upload_bps=upload_bps,
                    latency_ms=latency_ms,
                    packet_loss=packet_loss,
                    created_at=created_at or datetime.now(timezone.utc),
                )
            )
            session.commit()

    def traffic_samples(self, hours: int = 24, limit: int = 5000) -> list[TrafficSample]:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(1, hours))
        statement = (
            select(TrafficSample)
            .where(TrafficSample.created_at >= cutoff)
            .order_by(TrafficSample.created_at.desc())
            .limit(max(1, min(limit, 20_000)))
        )
        with Session(self.engine) as session:
            samples = list(session.scalars(statement))
        samples.reverse()
        return samples

    def prune_traffic(self, retention_days: int) -> int:
        cutoff = datetime.now(timezone.utc) - timedelta(days=max(1, retention_days))
        with Session(self.engine) as session:
            result = session.execute(delete(TrafficSample).where(TrafficSample.created_at < cutoff))
            session.commit()
            return int(result.rowcount or 0)

    def upsert_device(
        self, ip: str, mac: str, hostname: str | None, source: str = "LAN/ARP"
    ) -> bool:
        now = datetime.now(timezone.utc)
        normalized = mac.upper()
        with Session(self.engine) as session:
            device = session.scalar(
                select(KnownDevice).where(KnownDevice.mac_address == normalized)
            )
            is_new = device is None
            if device is None:
                device = KnownDevice(
                    ip_address=ip,
                    mac_address=normalized,
                    hostname=hostname,
                    source=source,
                    first_seen=now,
                    last_seen=now,
                    reachable=True,
                )
                session.add(device)
            else:
                device.ip_address = ip
                device.hostname = hostname or device.hostname
                device.source = source
                device.last_seen = now
                device.reachable = True
            session.commit()
            return is_new

    def devices(self) -> list[KnownDevice]:
        with Session(self.engine) as session:
            return list(
                session.scalars(select(KnownDevice).order_by(KnownDevice.last_seen.desc()))
            )

    def rename_device(self, mac: str, name: str) -> None:
        with Session(self.engine) as session:
            device = session.scalar(
                select(KnownDevice).where(KnownDevice.mac_address == mac.upper())
            )
            if device:
                device.custom_name = name.strip() or None
                session.commit()

    def audit(self, action: str, target: str, result: str, detail: str = "") -> None:
        with Session(self.engine) as session:
            session.add(AuditLog(action=action, target=target, result=result, detail=detail))
            session.commit()

    def audit_logs(self, limit: int = 500, action_prefix: str | None = None) -> list[AuditLog]:
        statement = select(AuditLog).order_by(AuditLog.created_at.desc()).limit(
            max(1, min(limit, 5000))
        )
        if action_prefix:
            statement = statement.where(AuditLog.action.like(f"{action_prefix}%"))
        with Session(self.engine) as session:
            return list(session.scalars(statement))

    def alert(self, kind: str, severity: str, message: str, target: str = "network") -> None:
        self.audit(f"alert:{kind}", target, severity, message)

