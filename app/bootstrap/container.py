from __future__ import annotations

from dataclasses import dataclass

from app.capabilities.automation import AutomationCapability
from app.capabilities.caller_lookup import CallerLookupCapability
from app.capabilities.knowledge import KnowledgeCapability
from app.capabilities.memory import MemoryCapability
from app.capabilities.phone_bridge import PhoneBridgeCapability
from app.capabilities.reminders import ReminderCapability
from app.capabilities.research import ResearchCapability
from app.capabilities.vision import VisionCapability
from app.capabilities.wake_on_lan import WakeOnLanCapability
from app.core.intent_router import IntentRouter
from app.core.orchestrator import AssistantOrchestrator
from app.services.acknowledgement_service import AcknowledgementService, DynamicPhraseGenerator
from app.services.automation_service import AutomationService
from app.services.brain_service import BrainService
from app.services.caller_lookup_service import CallerLookupService
from app.services.chat_service import ChatService
from app.services.fast_intent_router_service import FastIntentRouterService
from app.services.groq_service import GroqService
from app.services.interrupt_manager import InterruptManager
from app.services.personal_memory_service import PersonalMemoryService
from app.services.phone_command_service import PhoneCommandService
from app.services.realtime_service import RealtimeGroqService
from app.services.reminder_service import ReminderService
from app.services.research_tools_service import ResearchToolsService
from app.services.task_executor import TaskExecutor
from app.services.task_manager import TaskManager
from app.services.vector_store import VectorStoreService
from app.services.vision_service import VisionService
from app.services.wake_on_lan_service import WakeOnLanService
from app.services.command_risk_service import CommandRiskService
from app.services.face_enrollment_service import FaceEnrollmentService
from app.services.face_identity_service import FaceIdentityService
from app.services.launcher_bootstrap_service import LauncherBootstrapService
from app.services.step_up_auth_service import StepUpAuthService


@dataclass(slots=True)
class AppContainer:
    vector_store_service: VectorStoreService
    groq_service: GroqService
    realtime_service: RealtimeGroqService
    brain_service: BrainService
    task_executor: TaskExecutor
    task_manager: TaskManager
    vision_service: VisionService
    chat_service: ChatService
    automation_service: AutomationService
    caller_lookup_service: CallerLookupService
    phone_command_service: PhoneCommandService
    wake_on_lan_service: WakeOnLanService
    reminder_service: ReminderService
    research_tools_service: ResearchToolsService
    fast_intent_router_service: FastIntentRouterService
    acknowledgement_service: AcknowledgementService
    face_identity_service: FaceIdentityService
    face_enrollment_service: FaceEnrollmentService
    launcher_bootstrap_service: LauncherBootstrapService
    command_risk_service: CommandRiskService
    step_up_auth_service: StepUpAuthService
    interrupt_manager: InterruptManager
    personal_memory_service: PersonalMemoryService
    intent_router: IntentRouter
    orchestrator: AssistantOrchestrator
    caller_lookup_capability: CallerLookupCapability
    phone_bridge_capability: PhoneBridgeCapability

    def shutdown(self) -> None:
        self.task_manager.shutdown()
        for session_id in list(self.chat_service.sessions.keys()):
            self.chat_service.save_chat_session(session_id)


def build_container() -> AppContainer:
    vector_store_service = VectorStoreService()
    vector_store_service.create_vector_store()
    groq_service = GroqService(vector_store_service)
    realtime_service = RealtimeGroqService(vector_store_service)
    caller_lookup_service = CallerLookupService(realtime_service)
    phone_command_service = PhoneCommandService()
    wake_on_lan_service = WakeOnLanService()
    brain_service = BrainService(groq_service=groq_service)
    task_executor = TaskExecutor(groq_service=groq_service)
    automation_service = AutomationService(groq_service=groq_service)
    automation_service.set_whatsapp_contacts_provider(phone_command_service.list_synced_contacts)
    task_executor.automation_service = automation_service
    reminder_service = ReminderService()
    research_tools_service = ResearchToolsService(groq_service=groq_service, realtime_service=realtime_service)
    acknowledgement_service = AcknowledgementService(DynamicPhraseGenerator())
    interrupt_manager = InterruptManager()
    face_identity_service = FaceIdentityService()
    face_enrollment_service = FaceEnrollmentService(face_identity_service)
    launcher_bootstrap_service = LauncherBootstrapService()
    command_risk_service = CommandRiskService()
    step_up_auth_service = StepUpAuthService(
        face_identity_service=face_identity_service,
        command_risk_service=command_risk_service,
    )
    face_identity_service.register_profile_delete_callback(step_up_auth_service.invalidate_all)
    face_identity_service.register_profile_delete_callback(launcher_bootstrap_service.invalidate_all)
    personal_memory_service = PersonalMemoryService()
    fast_intent_router_service = FastIntentRouterService(
        phone_command_service=phone_command_service,
        automation_service=automation_service,
        wake_on_lan_service=wake_on_lan_service,
        reminder_service=reminder_service,
        research_tools_service=research_tools_service,
        brain_service=brain_service,
    )
    task_manager = TaskManager(task_executor=task_executor)
    vision_service = VisionService()
    chat_service = ChatService(
        groq_service,
        realtime_service,
        brain_service,
        task_executor=task_executor,
        vision_service=vision_service,
        task_manager=task_manager,
        automation_service=automation_service,
        wake_on_lan_service=wake_on_lan_service,
        phone_command_service=phone_command_service,
        reminder_service=reminder_service,
        research_tools_service=research_tools_service,
    )

    memory_capability = MemoryCapability(personal_memory_service)
    knowledge_capability = KnowledgeCapability(chat_service)
    automation_capability = AutomationCapability(automation_service)
    reminder_capability = ReminderCapability(reminder_service)
    research_capability = ResearchCapability(research_tools_service)
    vision_capability = VisionCapability(vision_service)
    wake_on_lan_capability = WakeOnLanCapability(wake_on_lan_service)
    caller_lookup_capability = CallerLookupCapability(caller_lookup_service)
    phone_bridge_capability = PhoneBridgeCapability(phone_command_service, caller_lookup_service)
    intent_router = IntentRouter(
        fast_router=fast_intent_router_service,
        brain_service=brain_service,
    )
    orchestrator = AssistantOrchestrator(
        conversation_service=chat_service,
        intent_router=intent_router,
        knowledge_capability=knowledge_capability,
        automation_capability=automation_capability,
        phone_bridge_capability=phone_bridge_capability,
        reminder_capability=reminder_capability,
        research_capability=research_capability,
        vision_capability=vision_capability,
        wake_on_lan_capability=wake_on_lan_capability,
        memory_capability=memory_capability,
        face_identity_service=face_identity_service,
        command_risk_service=command_risk_service,
        step_up_auth_service=step_up_auth_service,
        task_executor=task_executor,
        task_manager=task_manager,
    )
    chat_service.orchestrator = orchestrator
    return AppContainer(
        vector_store_service=vector_store_service,
        groq_service=groq_service,
        realtime_service=realtime_service,
        brain_service=brain_service,
        task_executor=task_executor,
        task_manager=task_manager,
        vision_service=vision_service,
        chat_service=chat_service,
        automation_service=automation_service,
        caller_lookup_service=caller_lookup_service,
        phone_command_service=phone_command_service,
        wake_on_lan_service=wake_on_lan_service,
        reminder_service=reminder_service,
        research_tools_service=research_tools_service,
        fast_intent_router_service=fast_intent_router_service,
        acknowledgement_service=acknowledgement_service,
        face_identity_service=face_identity_service,
        face_enrollment_service=face_enrollment_service,
        launcher_bootstrap_service=launcher_bootstrap_service,
        command_risk_service=command_risk_service,
        step_up_auth_service=step_up_auth_service,
        interrupt_manager=interrupt_manager,
        personal_memory_service=personal_memory_service,
        intent_router=intent_router,
        orchestrator=orchestrator,
        caller_lookup_capability=caller_lookup_capability,
        phone_bridge_capability=phone_bridge_capability,
    )
