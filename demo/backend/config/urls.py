from django.urls import path

from gateway import views

urlpatterns = [
    path("api/harness-profile", views.harness_profile),
    path("api/harness/prompts", views.harness_prompts),
    path("api/harness/models", views.harness_models),
    path("api/harness/configuration", views.harness_configuration),
    path("api/harness/agent-card", views.harness_agent_card),
    path("api/harness/data/preview", views.harness_csv_preview),
    path("api/harness/evaluations", views.harness_evaluations),
    path("api/harness/evaluations/<str:identity>", views.harness_evaluation_result),
    path("api/agents", views.agents),
    path("api/prompts", views.prompts),
    path("api/joule-agent-card", views.joule_agent_card),
    path("api/grounding", views.grounding),
    path("api/grounding/documents", views.grounding_documents),
    path("api/grounding/query", views.grounding_query),
    path("api/tools", views.tools_catalog),
    path("api/data-snapshots", views.data_snapshots),
    path("api/data-snapshots/<str:name>", views.data_snapshot),
    path("api/chat/latest", views.latest_chat),
    path("api/chat/input", views.chat_pending_input),
    path("api/chat/stream", views.chat_stream),
    path("healthz", views.healthz),
    path("readyz", views.readyz),
]
