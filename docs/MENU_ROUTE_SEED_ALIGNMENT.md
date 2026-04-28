# MENU ROUTE SEED ALIGNMENT

## 1. 菜单 seed 定位

- `scripts/seed_system_base.py` 中的 `MENUS` 只维护左侧导航和可见业务入口。
- 菜单 seed 不是全量页面注册表，不负责覆盖所有详情页、编辑页、临时页。
- 目录节点使用 `menu_type_code="DIRECTORY"`，用于导航分组，不要求直接映射具体页面。

## 2. 前端静态路由定位

- 前端仍使用 `src/router/routes.ts` 作为真实可访问页面定义。
- 隐藏详情页通过 `meta.hidden=true` 管理展示状态。
- 隐藏详情页通过 `meta.activeMenu` 归属到左侧可见菜单入口。

## 3. 对齐规则

- seed 中 `visible_flag=1` 且 `menu_type_code="MENU"` 的 `route_path`，必须存在于前端静态路由中。
- 前端可见入口页面应在 seed 中存在对应菜单项。
- 隐藏详情页（如 `/ship/detail/:id`）不强制进入 seed。

## 4. 命名规则

- `menu_code`：使用大写下划线风格，如 `SYSTEM_CONFIG`。
- `route_path`：使用前端访问路径，以 `/` 开头。
- `component_path`：使用 `modules/...`，不带 `.vue` 后缀。

## 5. 新增页面流程

1. 先判断页面是否属于左侧导航入口。
2. 若是入口页面：同步新增/调整 seed `MENUS`。
3. 若不是入口页面：仅维护前端隐藏路由与 `activeMenu` 归属。

## 6. 阶段边界

- 当前阶段仍采用前端静态路由，不做菜单完全驱动路由。
- 不引入自动 AST 对齐或动态路由下发机制。
