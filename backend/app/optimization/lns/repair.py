"""Repair operators for LNS."""

from abc import ABC, abstractmethod
from typing import Optional
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.route import Route
from app.models.trip import Trip
from app.optimization.greedy.insertion import GreedyInsertion, InsertionOption
from app.optimization.regret.insertion import RegretInsertion
from app.optimization.lns.destroy import DestroyResult


class RepairOperator(ABC):
    """Base class for repair operators."""

    @abstractmethod
    def repair(
        self,
        db: Session,
        destroy_result: DestroyResult,
        all_routes: list[Route],
    ) -> list[InsertionOption]:
        """Repair a destroyed solution by reinserting removed trips.

        Args:
            db: Database session
            destroy_result: Result from destroy operation
            all_routes: All current routes (including modified ones)

        Returns:
            List of insertion options applied
        """
        pass


class GreedyRepair(RepairOperator):
    """Repairs using greedy best insertion."""

    def __init__(self, greedy_insertion: Optional[GreedyInsertion] = None):
        self.greedy_insertion = greedy_insertion or GreedyInsertion()

    def repair(
        self,
        db: Session,
        destroy_result: DestroyResult,
        all_routes: list[Route],
    ) -> list[InsertionOption]:
        committed_options = []

        for trip in destroy_result.removed_trips:
            result = self.greedy_insertion.assign_trip(db, trip)
            if result.success and result.insertion_option:
                # Apply insertion
                self.greedy_insertion.apply_insertion(db, result.insertion_option, trip)
                committed_options.append(result.insertion_option)
                # Refresh affected route
                db.refresh(result.insertion_option.route)

        return committed_options


class Regret2Repair(RepairOperator):
    """Repairs using Regret-2 insertion."""

    def __init__(self, regret_insertion: Optional[RegretInsertion] = None):
        from app.optimization.regret.insertion import regret_2_insertion
        self.regret_insertion = regret_insertion or regret_2_insertion

    def repair(
        self,
        db: Session,
        destroy_result: DestroyResult,
        all_routes: list[Route],
    ) -> list[InsertionOption]:
        return self.regret_insertion.repair(db, destroy_result.removed_trips, all_routes)


class Regret3Repair(RepairOperator):
    """Repairs using Regret-3 insertion."""

    def __init__(self, regret_insertion: Optional[RegretInsertion] = None):
        from app.optimization.regret.insertion import regret_3_insertion
        self.regret_insertion = regret_insertion or regret_3_insertion

    def repair(
        self,
        db: Session,
        destroy_result: DestroyResult,
        all_routes: list[Route],
    ) -> list[InsertionOption]:
        return self.regret_insertion.repair(db, destroy_result.removed_trips, all_routes)


# Instances
greedy_repair = GreedyRepair()
regret_2_repair = Regret2Repair()
regret_3_repair = Regret3Repair()