"""对象状态单元 — 叙事真相与状态形态的拥有者."""

from .authortemplate import (
    AuthorTemplate,
    EvidenceRef,
    TemplatePrinciple,
    TemplateRuntime,
)
from .authorkernel import (
    VALUE_VOCAB,
    VALUE_VOCAB_CONTRA_KEYWORDS,
    VALUE_VOCAB_DESCRIPTIONS,
    VALUE_VOCAB_KEYWORDS,
    VALUE_VOCAB_PRO_KEYWORDS,
    AuthorKernel,
    AuthorPrinciple,
    KernelStatus,
    PrincipleCategory,
    value_direction,
)
from .authormodel_v3 import (
    AuthorModelV3,
    AuthorPrincipleV3,
    CounterexampleSample,
    CrossWorkValidationResult,
    SupportingSample,
)
from .authormodule import AuthorModule
from .autonomous import (
    AutonomousDecision,
    AutonomousPolicy,
    AutonomousRun,
    AutonomousUsage,
    ProviderCallAudit,
    ProviderProfile,
)
from .causal_compiler import (
    CausalDerivation,
    CostPropagationAuditReport,
    RuleDeletionAuditReport,
)
from .causal_defense import (
    CausalRule,
    TimelineResolution,
)
from .character_policy import (
    CharacterActionProposal,
    CharacterPolicyState,
)
from .characterupdate import CharacterUpdate
from .charactermodel import CharacterModel
from .choicerecord import (
    CandidateRecord,
    ChoiceRecord,
    ChoiceLedgerEntry,
    HindsightStatus,
    RejectedRecord,
)
from .evaluator_precommit import EvaluatorPrecommit
from .factledger import FactEntry, FactLedger, ValidityInterval
from .foreshadowgraph import ForeshadowEntry, ForeshadowGraph
from .human_eval import (
    BlindedChapterPacket,
    HumanEvaluationSubmission,
    LongHorizonAuthorizationVerdict,
    LongHorizonPreconditionStatus,
)
from .judge_claim import JudgeClaim, ProseAnchor
from .longhorizon import (
    LongHorizonCheckpoint,
    ProseSummary,
    RollingLongHorizonSummary,
)
from .narrativestate import NarrativeState
from .orchestration import (
    ChapterFunctionAllocation,
    EmotionalPacing,
    InformationDensityBudget,
    OrchestrationState,
    PromisePayoffDebt,
    ReaderExpectationHorizon,
    RelationalTrajectory,
    ThreadRotation,
)
from .plotunit import PlotUnit
from .prose_candidate import ProseCandidate
from .qualitythresholds import (
    AccuracyReport,
    HoldoutReport,
    JudgePreferencePrediction,
    PreferencePair,
    QualityThresholds,
)
from .readerexpectation import ReaderExpectation, ReaderExpectationLedger
from .readerreport import ReaderDimension, ReaderExperienceReport
from .readerresponse import ReaderResponseRecord
from .reviewissue import ReviewIssue, ReviewReminder
from .scene_experience import SceneExperience
from .structural_search import (
    CandidatePrecommit,
    NearDuplicatePair,
    ParetoDimensionScores,
    RolloutEvaluation,
    RolloutStep,
    StructuralDiversityReport,
    StructuralProposal,
    StructuralSearchResult,
)
from .taste_stack import (
    G7RetirementNotice,
    Layer1HardGatesSummary,
    Layer2SpecializedAxesSummary,
    Layer3BlindEvalSummary,
    Layer4PassAuditSummary,
    Layer5HumanBlindEvalSummary,
    StyleDriftSummary,
    UnifiedQualityReport,
)
from .styleprofile import (
    MetaphorHit,
    StyleProfile,
    StyleQuantitativeStats,
    StyleRisk,
)
from .timebook import EraContext, TimeAnchor, TimeBook, TimeInitial, TimelineSpec
from .workspec import WorkSpec
from .worldmodel import WorldModel

__all__ = [
    "AuthorTemplate",
    "EvidenceRef",
    "TemplatePrinciple",
    "TemplateRuntime",
    "AuthorKernel",
    "AuthorModelV3",
    "AuthorModule",
    "AuthorPrinciple",
    "AuthorPrincipleV3",
    "AutonomousDecision",
    "BlindedChapterPacket",
    "CandidatePrecommit",
    "CandidateRecord",
    "CausalDerivation",
    "CausalRule",
    "ChapterFunctionAllocation",
    "CharacterActionProposal",
    "CharacterModel",
    "CharacterPolicyState",
    "CharacterUpdate",
    "ChoiceLedgerEntry",
    "ChoiceRecord",
    "CostPropagationAuditReport",
    "CounterexampleSample",
    "CrossWorkValidationResult",
    "EmotionalPacing",
    "EraContext",
    "EvaluatorPrecommit",
    "FactEntry",
    "FactLedger",
    "ForeshadowEntry",
    "ForeshadowGraph",
    "G7RetirementNotice",
    "HindsightStatus",
    "HoldoutReport",
    "HumanEvaluationSubmission",
    "InformationDensityBudget",
    "JudgeClaim",
    "JudgePreferencePrediction",
    "KernelStatus",
    "Layer1HardGatesSummary",
    "Layer2SpecializedAxesSummary",
    "Layer3BlindEvalSummary",
    "Layer4PassAuditSummary",
    "Layer5HumanBlindEvalSummary",
    "LongHorizonAuthorizationVerdict",
    "LongHorizonCheckpoint",
    "LongHorizonPreconditionStatus",
    "MetaphorHit",
    "NarrativeState",
    "NearDuplicatePair",
    "OrchestrationState",
    "ParetoDimensionScores",
    "PlotUnit",
    "PreferencePair",
    "PromisePayoffDebt",
    "ProseAnchor",
    "ProseCandidate",
    "ProseSummary",
    "ProviderProfile",
    "ProviderCallAudit",
    "PrincipleCategory",
    "QualityThresholds",
    "ReaderDimension",
    "ReaderExpectation",
    "ReaderExpectationHorizon",
    "ReaderExpectationLedger",
    "ReaderExperienceReport",
    "ReaderResponseRecord",
    "RejectedRecord",
    "RelationalTrajectory",
    "ReviewIssue",
    "ReviewReminder",
    "RolloutEvaluation",
    "RolloutStep",
    "RollingLongHorizonSummary",
    "RuleDeletionAuditReport",
    "SceneExperience",
    "StructuralDiversityReport",
    "StructuralProposal",
    "StructuralSearchResult",
    "StyleDriftSummary",
    "StyleProfile",
    "StyleQuantitativeStats",
    "StyleRisk",
    "SupportingSample",
    "ThreadRotation",
    "TimeAnchor",
    "TimeBook",
    "TimeInitial",
    "TimelineSpec",
    "UnifiedQualityReport",
    "VALUE_VOCAB",
    "VALUE_VOCAB_CONTRA_KEYWORDS",
    "VALUE_VOCAB_DESCRIPTIONS",
    "VALUE_VOCAB_KEYWORDS",
    "VALUE_VOCAB_PRO_KEYWORDS",
    "ValidityInterval",
    "WorkSpec",
    "WorldModel",
    "value_direction",
]
