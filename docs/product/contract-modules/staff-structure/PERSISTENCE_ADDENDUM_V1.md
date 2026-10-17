# Model discovery impact

Status: Accepted technical impact, 2026-10-17, DEV only.
The canonical app.models.registry.MODEL_MODULES must register
app.modules.organization_units.change_models. This is the existing model-discovery
interface, not a parallel metadata registry. Root owns the one-line registration.
The full offline release-reliability regression must enumerate all model modules
and prove canonical metadata completeness. No schema or runtime write is authorized
by model registration itself; migration0182 and the separate DEV gates still own it.
