import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "apps.api.server:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
        reload_dirs=["apps", "ai_core", "auxiliary_brain", "perception_brain", "verification_brain", "repair_brain", "presentation_brain", "evidence_engine", "task_runtime"],
        reload_excludes=[
            "runtime/generated/*",
            "runtime/traces/*",
            "runtime/logs/*",
            "runtime/cache/*",
            "runtime/registry/*",
            "runtime/uploads/*",
            "runtime/downloads/*",
            "runtime/profiles/*",
            "runtime/secrets/*",
        ],
    )
