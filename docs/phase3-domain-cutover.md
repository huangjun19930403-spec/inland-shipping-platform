# Phase 3 Domain / Service 主链重写

更新时间：2026-03-19
范围：仅完成 Domain/Service 主链接管，不做数据库大改。

---

## 1. 全局切换结论

1. `app/services/*.py` 已退出主舞台，主业务实现迁移到 `app/domain/*/service.py`。
2. `app/core/dependencies.py` 已改为注入 `app/domain/*` 服务。
3. `app/api/v1/*` 已改为调用 domain service，而非旧 `app/services/*`。
4. `domain/*/__init__.py` 不再 re-export `app.services.*`，改为导出本域 `service.py`。
5. 旧 `app/services/__init__.py` 已删除。

---

## 2. 按域说明

## 2.1 address 域

1. 新主链文件
   - API: `app/api/v1/standard_data/address.py`
   - Service/Domain: `app/domain/address/service.py`
   - Repository: `app/repositories/address_repository.py`
   - Model: `app/models/address.py`
2. 替换的旧 service
   - `app/services/address_service.py`
3. 删除的旧实现
   - 旧路径 `app/services/address_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/address_service.py` → `app/domain/address/service.py`
5. 当前真实链路
   - `standard_data/address API` → `AddressService` → `AddressRepository`（+ `AuditService`）

## 2.2 commodity 域

1. 新主链文件
   - API: `app/api/v1/standard_data/commodity.py`
   - Service/Domain: `app/domain/commodity/service.py`
   - Repository: `app/repositories/cargo_repository.py`（categories/types/standards/aliases 子仓储）
   - Model: `app/models/cargo.py`（commodity_* 系列）
2. 替换的旧 service
   - 旧 `CargoService` 中的 commodity 相关职责
3. 删除的旧实现
   - `app/domain/cargo/service.py` 中 commodity 逻辑已移除（职责拆分）
4. 迁移的旧实现
   - commodity 逻辑从旧 `app/services/cargo_service.py` 拆分迁入 `app/domain/commodity/service.py`
5. 当前真实链路
   - `standard_data/commodity API` → `CommodityService` → `CargoRepository`（+ `AuditService`）

## 2.3 vessel 域

1. 新主链文件
   - API: `app/api/v1/standard_data/vessel.py`, `app/api/v1/ingestion/vessel.py`
   - Service/Domain: `app/domain/vessel/service.py`
   - Repository: `app/repositories/vessel_repository.py`
   - Model: `app/models/vessel.py`
2. 替换的旧 service
   - `app/services/vessel_service.py`
3. 删除的旧实现
   - 旧路径 `app/services/vessel_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/vessel_service.py` → `app/domain/vessel/service.py`
5. 当前真实链路
   - `standard_data/vessel API` / `ingestion/vessel API` → `VesselService` → `VesselRepository`（+ `AuditService`）

## 2.4 cargo 域

1. 新主链文件
   - API: `app/api/v1/ingestion/cargo.py`
   - Service/Domain: `app/domain/cargo/service.py`
   - Repository: `app/repositories/cargo_repository.py`, `app/repositories/address_repository.py`, `app/repositories/ai_repository.py`
   - Model: `app/models/cargo.py`
2. 替换的旧 service
   - `app/services/cargo_service.py`（货源链路部分）
3. 删除的旧实现
   - 旧路径 `app/services/cargo_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/cargo_service.py` → `app/domain/cargo/service.py`（并剥离 commodity 职责）
5. 当前真实链路
   - `ingestion/cargo API` → `CargoService` → `CargoRepository/AddressRepository/AiRepository`（+ `AuditService`）

## 2.5 route 域

1. 新主链文件
   - API: `app/api/v1/standard_data/route.py`
   - Service/Domain: `app/domain/route/service.py`
   - Repository: `app/repositories/route_repository.py`
   - Model: `app/models/route.py`
2. 替换的旧 service
   - `app/services/route_service.py`
3. 删除的旧实现
   - 旧路径 `app/services/route_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/route_service.py` → `app/domain/route/service.py`
5. 当前真实链路
   - `standard_data/route API` → `RouteService` → `RouteRepository`

## 2.6 analysis 域

1. 新主链文件
   - API: `app/api/v1/analysis/router.py`
   - Service/Domain: `app/domain/analysis/service.py`
   - Repository: `app/repositories/analysis_repository.py`
   - Model: `app/models/analysis.py`
2. 替换的旧 service
   - `app/services/analysis_service.py`
3. 删除的旧实现
   - 旧路径 `app/services/analysis_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/analysis_service.py` → `app/domain/analysis/service.py`
5. 当前真实链路
   - `analysis API` → `AnalysisService` → `AnalysisRepository`（统计触发仍调用 `app/tasks/stat_tasks.py`）

## 2.7 audit 域

1. 新主链文件
   - API: `app/api/v1/system/audit.py`
   - Service/Domain: `app/domain/audit/service.py`
   - Repository: `app/repositories/audit_repository.py`
   - Model: `app/models/audit.py`
2. 替换的旧 service
   - `app/services/audit_service.py`
3. 删除的旧实现
   - 旧路径 `app/services/audit_service.py`（已从旧目录移除）
4. 迁移的旧实现
   - `app/services/audit_service.py` → `app/domain/audit/service.py`
5. 当前真实链路
   - `system/audit API` → `AuditService` → `AuditRepository`

---

## 3. 旧 services 处理结果

1. 已移除旧主目录文件（通过路径迁移）：
   - `app/services/address_service.py`
   - `app/services/cargo_service.py`
   - `app/services/vessel_service.py`
   - `app/services/route_service.py`
   - `app/services/analysis_service.py`
   - `app/services/audit_service.py`
2. 已删除：
   - `app/services/__init__.py`
3. 未迁入 legacy 的说明
   - 本阶段采用“直接迁移到 domain 正式主路径”的方式，不再保留旧 service 源码副本。

---

## 4. 当前 API -> Service -> Repository 真实链路总览

1. `standard_data/address` -> `domain.address.service.AddressService` -> `AddressRepository`
2. `standard_data/commodity` -> `domain.commodity.service.CommodityService` -> `CargoRepository`(commodity 子仓储)
3. `standard_data/vessel` + `ingestion/vessel` -> `domain.vessel.service.VesselService` -> `VesselRepository`
4. `ingestion/cargo` -> `domain.cargo.service.CargoService` -> `CargoRepository` / `AddressRepository` / `AiRepository`
5. `standard_data/route` -> `domain.route.service.RouteService` -> `RouteRepository`
6. `analysis` -> `domain.analysis.service.AnalysisService` -> `AnalysisRepository`
7. `system/audit` -> `domain.audit.service.AuditService` -> `AuditRepository`

以上链路已替换旧 `app/services/*` 主职责，domain/service 已为真实实现而非转发层。
