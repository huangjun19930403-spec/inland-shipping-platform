-- ============================================================
-- 内河航运平台 - MySQL 8.0 初始化建表脚本
-- 生成时间: 2026-03-16
-- 字符集: utf8mb4 / utf8mb4_unicode_ci
-- 引擎: InnoDB
-- 执行方式: mysql -u root -p < docs/init_mysql.sql
-- ============================================================

CREATE DATABASE IF NOT EXISTS inland_shipping
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE inland_shipping;

SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;


-- ============================================================
-- 模块一：系统基础（sys_role / sys_user / sys_user_role）
-- ============================================================

CREATE TABLE IF NOT EXISTS `sys_role` (
  `id`          INT          NOT NULL AUTO_INCREMENT         COMMENT '主键',
  `code`        VARCHAR(32)  NOT NULL                        COMMENT '角色编码: SUPER_ADMIN/ADMIN/OPERATOR/COLLECTOR',
  `name`        VARCHAR(64)  NOT NULL                        COMMENT '角色名称',
  `description` VARCHAR(256)                                 COMMENT '角色描述',
  `status`      TINYINT      NOT NULL DEFAULT 1              COMMENT '1=启用,0=停用',
  `sort_order`  TINYINT      NOT NULL DEFAULT 0              COMMENT '排序',
  `created_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sys_role_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统角色表';


CREATE TABLE IF NOT EXISTS `sys_user` (
  `id`            INT          NOT NULL AUTO_INCREMENT         COMMENT '主键',
  `username`      VARCHAR(64)  NOT NULL                        COMMENT '用户名（登录名）',
  `real_name`     VARCHAR(64)  NOT NULL                        COMMENT '真实姓名',
  `password_hash` VARCHAR(256) NOT NULL                        COMMENT '密码哈希',
  `phone`         VARCHAR(32)                                  COMMENT '手机号',
  `email`         VARCHAR(128)                                 COMMENT '邮箱',
  `department`    VARCHAR(64)                                  COMMENT '部门',
  `avatar`        VARCHAR(256)                                 COMMENT '头像URL',
  `wx_open_id`    VARCHAR(64)                                  COMMENT '微信OpenID',
  `wx_bound`      TINYINT               DEFAULT 0              COMMENT '0=未绑定,1=已绑定',
  `status`        TINYINT      NOT NULL DEFAULT 1              COMMENT '1=启用,0=停用',
  `last_login_at` DATETIME                                     COMMENT '最后登录时间',
  `created_by`    BIGINT                                       COMMENT '创建人ID',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sys_user_username` (`username`),
  KEY `idx_sys_user_wx_open_id` (`wx_open_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='系统用户表';


CREATE TABLE IF NOT EXISTS `sys_user_role` (
  `id`         INT      NOT NULL AUTO_INCREMENT COMMENT '主键',
  `user_id`    BIGINT   NOT NULL               COMMENT '用户ID',
  `role_id`    BIGINT   NOT NULL               COMMENT '角色ID',
  `created_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_user_role` (`user_id`, `role_id`),
  KEY `idx_sur_user_id` (`user_id`),
  KEY `idx_sur_role_id` (`role_id`),
  CONSTRAINT `fk_sur_user_id` FOREIGN KEY (`user_id`) REFERENCES `sys_user` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_sur_role_id` FOREIGN KEY (`role_id`) REFERENCES `sys_role` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='用户角色关联表';


-- ============================================================
-- 模块二：审核记录（audit_record）
-- ============================================================

CREATE TABLE IF NOT EXISTS `audit_record` (
  `id`             INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `target_type`    VARCHAR(64)  NOT NULL               COMMENT '审核对象类型: TRANSPORT_NODE/COMMODITY_CATEGORY/COMMODITY_TYPE/COMMODITY_STANDARD/VESSEL/WATERWAY/REGION/NODE_TYPE/CARGO_OPPORTUNITY',
  `target_id`      BIGINT       NOT NULL               COMMENT '被审核对象ID',
  `target_name`    VARCHAR(256)                        COMMENT '被审核对象名称（快照）',
  `action`         VARCHAR(32)  NOT NULL               COMMENT '操作类型: CREATE/UPDATE/DISABLE/ENABLE/AI_CONFIRM',
  `before_data`    JSON                                COMMENT '变更前数据快照',
  `after_data`     JSON                                COMMENT '变更后数据快照（提交内容）',
  `audit_result`   VARCHAR(32)  NOT NULL               COMMENT 'PENDING/APPROVED/REJECTED',
  `audit_remark`   VARCHAR(512)                        COMMENT '审核意见',
  `submitter_id`   BIGINT       NOT NULL               COMMENT '提交人ID',
  `submitter_name` VARCHAR(64)                         COMMENT '提交人姓名（快照）',
  `submitted_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '提交时间',
  `auditor_id`     BIGINT                              COMMENT '审核人ID',
  `auditor_name`   VARCHAR(64)                         COMMENT '审核人姓名（快照）',
  `audited_at`     DATETIME                            COMMENT '审核时间',
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ar_target` (`target_type`, `target_id`),
  KEY `idx_ar_submitter` (`submitter_id`),
  KEY `idx_ar_result` (`audit_result`),
  KEY `idx_ar_submitted_at` (`submitted_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='审核记录表';


-- ============================================================
-- 模块三：地址体系
-- 建表顺序: waterway → admin_region → node_type → region
--           → transport_node → node_alias → region_address_relation
-- ============================================================

CREATE TABLE IF NOT EXISTS `waterway` (
  `id`                  INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`                VARCHAR(32)   NOT NULL               COMMENT '水系编码（格式 WW-LL-NNN）',
  `name`                VARCHAR(64)   NOT NULL               COMMENT '水系名称',
  `name_en`             VARCHAR(128)                         COMMENT '英文名称',
  `level`               TINYINT       NOT NULL DEFAULT 1     COMMENT '1=主干水系,2=支流,3=运河',
  `parent_id`           BIGINT                               COMMENT '上级水系ID（自关联）',
  `provinces`           VARCHAR(256)                         COMMENT '流经省份',
  `total_length_km`     DECIMAL(10,2)                        COMMENT '总长度(km)',
  `navigable_length_km` DECIMAL(10,2)                        COMMENT '通航里程(km)',
  `description`         VARCHAR(512)                         COMMENT '描述',
  `sort_order`          INT           NOT NULL DEFAULT 0     COMMENT '排序',
  `status`              TINYINT       NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_waterway_code` (`code`),
  KEY `idx_waterway_parent_id` (`parent_id`),
  KEY `idx_waterway_status` (`status`),
  CONSTRAINT `fk_waterway_parent` FOREIGN KEY (`parent_id`) REFERENCES `waterway` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='水系表';


CREATE TABLE IF NOT EXISTS `admin_region` (
  `id`          INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`        VARCHAR(12)   NOT NULL               COMMENT '行政区划代码（国标）',
  `name`        VARCHAR(64)   NOT NULL               COMMENT '名称',
  `short_name`  VARCHAR(32)                          COMMENT '简称',
  `pinyin`      VARCHAR(128)                         COMMENT '拼音',
  `level`       TINYINT       NOT NULL               COMMENT '1=省,2=市,3=区县',
  `parent_code` VARCHAR(12)                          COMMENT '上级代码（自关联）',
  `full_path`   VARCHAR(256)                         COMMENT '完整路径（如：湖北省/武汉市/武昌区）',
  `longitude`   DECIMAL(11,8)                        COMMENT '行政中心经度',
  `latitude`    DECIMAL(10,8)                        COMMENT '行政中心纬度',
  `sort_order`  INT                    DEFAULT 0     COMMENT '排序',
  `status`      TINYINT       NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_at`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`  DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_admin_region_code` (`code`),
  KEY `idx_ar_parent_code` (`parent_code`),
  KEY `idx_ar_level` (`level`),
  CONSTRAINT `fk_ar_parent_code` FOREIGN KEY (`parent_code`) REFERENCES `admin_region` (`code`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='行政区划表';


CREATE TABLE IF NOT EXISTS `node_type` (
  `id`             INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`           VARCHAR(32)  NOT NULL               COMMENT '类型编码',
  `name`           VARCHAR(64)  NOT NULL               COMMENT '类型名称',
  `name_en`        VARCHAR(128)                        COMMENT '英文名称',
  `transport_mode` VARCHAR(32)  NOT NULL DEFAULT 'WATERWAY' COMMENT 'WATERWAY/RAILWAY/HIGHWAY/MULTIMODAL',
  `icon`           VARCHAR(256)                        COMMENT '图标URL',
  `description`    VARCHAR(512)                        COMMENT '描述',
  `sort_order`     INT          NOT NULL DEFAULT 0     COMMENT '排序',
  `status`         TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`     DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_type_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='节点类型字典表';


CREATE TABLE IF NOT EXISTS `region` (
  `id`                  INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`                VARCHAR(50)   NOT NULL               COMMENT '区域编码（系统自动生成，格式 RG-NNN）',
  `name`                VARCHAR(64)   NOT NULL               COMMENT '区域名称',
  `name_en`             VARCHAR(128)                         COMMENT '英文名称',
  `center_longitude`    DECIMAL(11,8)                        COMMENT '区域中心经度（由边界坐标自动计算）',
  `center_latitude`     DECIMAL(10,8)                        COMMENT '区域中心纬度（由边界坐标自动计算）',
  `main_rivers`         JSON                                 COMMENT '主要水系 ID 数组（Waterway.id）',
  `main_cities`         JSON                                 COMMENT '主要城市 ID 数组（AdminRegion.id，由边界自动计算）',
  `boundary_coordinates` JSON                                COMMENT '边界坐标点序列 [[lng,lat],...]',
  `boundary_color`      VARCHAR(20)            DEFAULT '#3388ff' COMMENT '边界颜色',
  `area_color`          VARCHAR(20)            DEFAULT '#3388ff' COMMENT '填充颜色',
  `description`         VARCHAR(512)                         COMMENT '描述',
  `sort_order`          INT           NOT NULL DEFAULT 0     COMMENT '排序',
  `status`              TINYINT       NOT NULL DEFAULT 0     COMMENT '1=启用,0=停用',
  `audit_status`        TINYINT       NOT NULL DEFAULT 0     COMMENT '0=待审核,1=已通过,2=已驳回',
  `audit_remark`        VARCHAR(512)                         COMMENT '审核意见',
  `submitter_id`        BIGINT                               COMMENT '提交人ID',
  `auditor_id`          BIGINT                               COMMENT '审核人ID',
  `created_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`          DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_region_code` (`code`),
  KEY `idx_region_status` (`status`),
  KEY `idx_region_audit_status` (`audit_status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='航运商业区域表';


CREATE TABLE IF NOT EXISTS `transport_node` (
  `id`                INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`              VARCHAR(32)   NOT NULL               COMMENT '节点编码',
  `name`              VARCHAR(128)  NOT NULL               COMMENT '节点标准名称',
  `name_en`           VARCHAR(256)                         COMMENT '英文名称',
  `node_type_id`      BIGINT        NOT NULL               COMMENT '节点类型ID',
  `node_category`     TINYINT       NOT NULL DEFAULT 4     COMMENT '1=装货,2=卸货,3=中转,4=综合,5=航道',
  `waterway_id`       BIGINT                               COMMENT '所属水系ID',
  `region_id`         BIGINT                               COMMENT '所属商业区域ID',
  `province`          VARCHAR(32)                          COMMENT '所属省份',
  `city`              VARCHAR(32)                          COMMENT '所属城市',
  `district`          VARCHAR(32)                          COMMENT '所属区县',
  `address`           VARCHAR(256)                         COMMENT '详细地址',
  `longitude`         DECIMAL(11,8)                        COMMENT '经度(WGS84)',
  `latitude`          DECIMAL(10,8)                        COMMENT '纬度(WGS84)',
  `node_level`        TINYINT                DEFAULT 3     COMMENT '1=一级,2=二级,3=三级',
  `is_hot_node`       TINYINT       NOT NULL DEFAULT 0     COMMENT '0=否,1=是',
  `river_km`          DECIMAL(10,2)                        COMMENT '航道里程标(km)',
  `max_tonnage`       INT                                  COMMENT '最大靠泊吨位(吨)',
  `berth_count`       INT                                  COMMENT '泊位数量',
  `annual_throughput` VARCHAR(64)                          COMMENT '年吞吐量',
  `description`       VARCHAR(512)                         COMMENT '描述',
  `sort_order`        INT           NOT NULL DEFAULT 0     COMMENT '排序',
  `status`            TINYINT       NOT NULL DEFAULT 1     COMMENT '1=运营中,0=停用,2=建设中',
  `audit_status`      TINYINT                DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `audit_remark`      VARCHAR(512)                         COMMENT '审核意见',
  `submitter_id`      BIGINT                               COMMENT '提交人ID',
  `auditor_id`        BIGINT                               COMMENT '审核人ID',
  `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_transport_node_code` (`code`),
  KEY `idx_tn_waterway_id` (`waterway_id`),
  KEY `idx_tn_region_id` (`region_id`),
  KEY `idx_tn_node_type_id` (`node_type_id`),
  KEY `idx_tn_status` (`status`),
  KEY `idx_tn_audit_status` (`audit_status`),
  KEY `idx_tn_is_hot` (`is_hot_node`),
  CONSTRAINT `fk_tn_node_type` FOREIGN KEY (`node_type_id`) REFERENCES `node_type` (`id`),
  CONSTRAINT `fk_tn_waterway`  FOREIGN KEY (`waterway_id`)  REFERENCES `waterway` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_tn_region`    FOREIGN KEY (`region_id`)    REFERENCES `region` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='运输节点表';


CREATE TABLE IF NOT EXISTS `node_alias` (
  `id`                INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `node_id`           BIGINT       NOT NULL               COMMENT '所属节点ID',
  `alias_name`        VARCHAR(128) NOT NULL               COMMENT '别名',
  `alias_type`        VARCHAR(32)  NOT NULL DEFAULT 'COMMON' COMMENT 'COMMON/ABBR/HISTORICAL/SYSTEM',
  `source`            VARCHAR(64)                         COMMENT '别名来源',
  `priority`          INT          NOT NULL DEFAULT 0     COMMENT '匹配优先级（越大越优先）',
  `status`            TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_node_alias_name` (`alias_name`),
  KEY `idx_na_node_id` (`node_id`),
  CONSTRAINT `fk_na_node_id` FOREIGN KEY (`node_id`) REFERENCES `transport_node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='节点别名表';


CREATE TABLE IF NOT EXISTS `region_address_relation` (
  `id`                INT      NOT NULL AUTO_INCREMENT COMMENT '主键',
  `region_id`         BIGINT   NOT NULL               COMMENT '区域ID',
  `transport_node_id` BIGINT   NOT NULL               COMMENT '节点ID',
  `is_primary`        TINYINT  NOT NULL DEFAULT 1     COMMENT '1=主归属',
  `created_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_rar_region_node` (`region_id`, `transport_node_id`),
  KEY `idx_rar_node_id` (`transport_node_id`),
  CONSTRAINT `fk_rar_region_id` FOREIGN KEY (`region_id`)         REFERENCES `region` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_rar_node_id`   FOREIGN KEY (`transport_node_id`) REFERENCES `transport_node` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='节点与区域关系表';


-- ============================================================
-- 模块四：货品体系
-- 建表顺序: commodity_category → commodity_type → commodity_standard → commodity_alias
-- ============================================================

CREATE TABLE IF NOT EXISTS `commodity_category` (
  `id`           INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`         VARCHAR(32)                         COMMENT '分类编码',
  `name`         VARCHAR(64)  NOT NULL               COMMENT '大类名称',
  `name_en`      VARCHAR(128)                        COMMENT '英文名称',
  `description`  VARCHAR(512)                        COMMENT '描述',
  `sort_order`   INT          NOT NULL DEFAULT 0     COMMENT '排序',
  `status`       TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `audit_status` TINYINT               DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `submitter_id` BIGINT                              COMMENT '提交人ID',
  `auditor_id`   BIGINT                              COMMENT '审核人ID',
  `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_cc_status` (`status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='货品大类表';


CREATE TABLE IF NOT EXISTS `commodity_type` (
  `id`           INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `category_id`  BIGINT       NOT NULL               COMMENT '所属大类ID',
  `code`         VARCHAR(32)                         COMMENT '类型编码',
  `name`         VARCHAR(64)  NOT NULL               COMMENT '类型名称',
  `name_en`      VARCHAR(128)                        COMMENT '英文名称',
  `description`  VARCHAR(512)                        COMMENT '描述',
  `sort_order`   INT          NOT NULL DEFAULT 0     COMMENT '排序',
  `status`       TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `audit_status` TINYINT               DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `submitter_id` BIGINT                              COMMENT '提交人ID',
  `auditor_id`   BIGINT                              COMMENT '审核人ID',
  `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ct_category_id` (`category_id`),
  KEY `idx_ct_status` (`status`),
  CONSTRAINT `fk_ct_category_id` FOREIGN KEY (`category_id`) REFERENCES `commodity_category` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='货品类型表';


CREATE TABLE IF NOT EXISTS `commodity_standard` (
  `id`                     INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `type_id`                BIGINT        NOT NULL               COMMENT '所属类型ID',
  `code`                   VARCHAR(32)                          COMMENT '货品编码',
  `name`                   VARCHAR(128)  NOT NULL               COMMENT '货品标准名称',
  `name_en`                VARCHAR(256)                         COMMENT '英文名称',
  `commodity_class`        VARCHAR(32)                          COMMENT '货品分类: 散货/件杂/液体/集装箱/特种',
  `industry`               VARCHAR(64)                          COMMENT '行业分类',
  `density`                DECIMAL(8,4)                         COMMENT '密度(t/m³)',
  `is_dangerous`           TINYINT                DEFAULT 0     COMMENT '0=否,1=是',
  `loading_method`         VARCHAR(64)                          COMMENT '装货方式',
  `recommended_ship_type`  VARCHAR(128)                         COMMENT '推荐船型',
  `description`            VARCHAR(512)                         COMMENT '描述',
  `sort_order`             INT           NOT NULL DEFAULT 0     COMMENT '排序',
  `status`                 TINYINT       NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `audit_status`           TINYINT                DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `audit_remark`           VARCHAR(512)                         COMMENT '审核意见',
  `submitter_id`           BIGINT                               COMMENT '提交人ID',
  `auditor_id`             BIGINT                               COMMENT '审核人ID',
  `created_at`             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`             DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_cs_type_id` (`type_id`),
  KEY `idx_cs_status` (`status`),
  KEY `idx_cs_is_dangerous` (`is_dangerous`),
  CONSTRAINT `fk_cs_type_id` FOREIGN KEY (`type_id`) REFERENCES `commodity_type` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='标准货品表';


CREATE TABLE IF NOT EXISTS `commodity_alias` (
  `id`           INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `commodity_id` BIGINT       NOT NULL               COMMENT '所属标准货品ID',
  `alias_name`   VARCHAR(128) NOT NULL               COMMENT '别名',
  `alias_type`   VARCHAR(32)           DEFAULT 'COMMON' COMMENT 'COMMON/ABBR/DIALECT/INDUSTRY',
  `priority`     INT          NOT NULL DEFAULT 0     COMMENT '匹配优先级',
  `status`       TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_ca_commodity_id` (`commodity_id`),
  KEY `idx_ca_alias_name` (`alias_name`),
  CONSTRAINT `fk_ca_commodity_id` FOREIGN KEY (`commodity_id`) REFERENCES `commodity_standard` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='货品别名表';


-- ============================================================
-- 模块五：货源体系
-- 建表顺序: cargo_raw_message → cargo_ai_parse_result → cargo_opportunity
-- ============================================================

CREATE TABLE IF NOT EXISTS `cargo_raw_message` (
  `id`           INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `raw_text`     TEXT         NOT NULL               COMMENT '原始文本内容',
  `source_type`  VARCHAR(32)           DEFAULT 'WECHAT_GROUP' COMMENT 'WECHAT_GROUP/PHONE/WEBSITE/OTHER',
  `group_name`   VARCHAR(128)                        COMMENT '群名称',
  `sender_name`  VARCHAR(64)                         COMMENT '发送人',
  `message_time` DATETIME                            COMMENT '消息时间',
  `collector_id` BIGINT                              COMMENT '采集员ID',
  `status`       VARCHAR(32)           DEFAULT 'PENDING' COMMENT 'PENDING/PARSING/PARSED/INVALID',
  `created_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_crm_status` (`status`),
  KEY `idx_crm_collector_id` (`collector_id`),
  KEY `idx_crm_message_time` (`message_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='原始货源文本表';


CREATE TABLE IF NOT EXISTS `cargo_ai_parse_result` (
  `id`                   INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `raw_message_id`       BIGINT        NOT NULL               COMMENT '原始文本ID',
  `origin_text`          VARCHAR(256)                         COMMENT '起点原始文本',
  `dest_text`            VARCHAR(256)                         COMMENT '终点原始文本',
  `commodity_text`       VARCHAR(256)                         COMMENT '货品原始文本',
  `tonnage_text`         VARCHAR(64)                          COMMENT '吨位原始文本',
  `loading_date_text`    VARCHAR(64)                          COMMENT '时间原始文本',
  `freight_text`         VARCHAR(128)                         COMMENT '运价原始文本',
  `contact_text`         VARCHAR(256)                         COMMENT '联系方式原始文本',
  `origin_node_id`       BIGINT                               COMMENT '匹配的起点节点ID',
  `dest_node_id`         BIGINT                               COMMENT '匹配的终点节点ID',
  `commodity_id`         BIGINT                               COMMENT '匹配的货品ID',
  `tonnage`              DECIMAL(12,2)                        COMMENT '解析的吨位',
  `loading_date`         DATE                                 COMMENT '解析的装货日期',
  `freight_price`        DECIMAL(12,2)                        COMMENT '解析的运价',
  `price_type`           TINYINT                              COMMENT '计价方式: 1=按吨,2=按方,3=包干,4=按箱,5=面议',
  `contact_person`       VARCHAR(64)                          COMMENT '解析的联系人',
  `contact_phone`        VARCHAR(32)                          COMMENT '解析的联系电话',
  `origin_confidence`    INT                    DEFAULT 0     COMMENT '起点置信度(0-100)',
  `dest_confidence`      INT                    DEFAULT 0     COMMENT '终点置信度(0-100)',
  `commodity_confidence` INT                    DEFAULT 0     COMMENT '货品置信度(0-100)',
  `tonnage_confidence`   INT                    DEFAULT 0     COMMENT '吨位置信度(0-100)',
  `overall_confidence`   INT                    DEFAULT 0     COMMENT '综合置信度(0-100)',
  `origin_candidates`    JSON                                 COMMENT '起点候选列表 [{id,name,score}]',
  `dest_candidates`      JSON                                 COMMENT '终点候选列表',
  `commodity_candidates` JSON                                 COMMENT '货品候选列表',
  `ai_model`             VARCHAR(64)                          COMMENT '使用的AI模型',
  `ai_prompt_tokens`     INT                                  COMMENT '消耗的tokens数',
  `parse_status`         VARCHAR(32)            DEFAULT 'PENDING_CONFIRM' COMMENT 'PENDING_CONFIRM/CONFIRMED/DISCARDED',
  `confirmed_by`         BIGINT                               COMMENT '确认人ID',
  `confirmed_at`         DATETIME                             COMMENT '确认时间',
  `discard_reason`       VARCHAR(256)                         COMMENT '废弃原因',
  `created_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_capr_raw_message_id` (`raw_message_id`),
  KEY `idx_capr_parse_status` (`parse_status`),
  KEY `idx_capr_origin_node_id` (`origin_node_id`),
  KEY `idx_capr_dest_node_id` (`dest_node_id`),
  CONSTRAINT `fk_capr_raw_message`  FOREIGN KEY (`raw_message_id`) REFERENCES `cargo_raw_message` (`id`),
  CONSTRAINT `fk_capr_origin_node`  FOREIGN KEY (`origin_node_id`) REFERENCES `transport_node` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_capr_dest_node`    FOREIGN KEY (`dest_node_id`)   REFERENCES `transport_node` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_capr_commodity_id` FOREIGN KEY (`commodity_id`)   REFERENCES `commodity_standard` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='AI解析结果表';


CREATE TABLE IF NOT EXISTS `cargo_opportunity` (
  `id`               INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `opportunity_no`   VARCHAR(32)   NOT NULL               COMMENT '货源编号（唯一）',
  `origin_node_id`   BIGINT        NOT NULL               COMMENT '装货节点ID',
  `dest_node_id`     BIGINT        NOT NULL               COMMENT '卸货节点ID',
  `commodity_id`     BIGINT        NOT NULL               COMMENT '货品ID',
  `tonnage`          DECIMAL(12,2) NOT NULL               COMMENT '货物吨位(吨)',
  `origin_region_id` BIGINT                               COMMENT '装货区域ID（系统自动）',
  `dest_region_id`   BIGINT                               COMMENT '卸货区域ID（系统自动）',
  `route_id`         BIGINT                               COMMENT '匹配航线ID（系统自动）',
  `loading_date`     DATE                                 COMMENT '装货日期',
  `freight_price`    DECIMAL(12,2)                        COMMENT '运价',
  `price_type`       TINYINT                              COMMENT '1=按吨,2=按方,3=包干,4=按箱,5=面议',
  `price_unit`       VARCHAR(32)                          COMMENT '计价单位: 元/吨,元/方等',
  `contact_person`   VARCHAR(64)                          COMMENT '联系人',
  `contact_phone`    VARCHAR(32)                          COMMENT '联系电话',
  `source_type`      VARCHAR(32)            DEFAULT 'WECHAT_GROUP' COMMENT '来源: WECHAT_GROUP/PHONE/WEBSITE/OTHER',
  `remark`           VARCHAR(512)                         COMMENT '备注',
  `raw_message_id`   BIGINT                               COMMENT '原始文本ID（溯源）',
  `parse_result_id`  BIGINT                               COMMENT 'AI解析结果ID（溯源）',
  `status`           VARCHAR(32)            DEFAULT 'CONFIRMED' COMMENT 'PENDING_CONFIRM/CONFIRMED/CANCELLED',
  `input_type`       VARCHAR(32)            DEFAULT 'MANUAL' COMMENT '录入方式: MANUAL/AI_PARSE',
  `collector_id`     BIGINT                               COMMENT '采集员ID',
  `created_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_co_opportunity_no` (`opportunity_no`),
  KEY `idx_co_origin_node_id` (`origin_node_id`),
  KEY `idx_co_dest_node_id` (`dest_node_id`),
  KEY `idx_co_commodity_id` (`commodity_id`),
  KEY `idx_co_origin_region_id` (`origin_region_id`),
  KEY `idx_co_dest_region_id` (`dest_region_id`),
  KEY `idx_co_route_id` (`route_id`),
  KEY `idx_co_loading_date` (`loading_date`),
  KEY `idx_co_status` (`status`),
  CONSTRAINT `fk_co_origin_node`    FOREIGN KEY (`origin_node_id`)   REFERENCES `transport_node` (`id`),
  CONSTRAINT `fk_co_dest_node`      FOREIGN KEY (`dest_node_id`)     REFERENCES `transport_node` (`id`),
  CONSTRAINT `fk_co_commodity`      FOREIGN KEY (`commodity_id`)     REFERENCES `commodity_standard` (`id`),
  CONSTRAINT `fk_co_origin_region`  FOREIGN KEY (`origin_region_id`) REFERENCES `region` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_co_dest_region`    FOREIGN KEY (`dest_region_id`)   REFERENCES `region` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_co_raw_message`    FOREIGN KEY (`raw_message_id`)   REFERENCES `cargo_raw_message` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_co_parse_result`   FOREIGN KEY (`parse_result_id`)  REFERENCES `cargo_ai_parse_result` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='货源信息表（正式数据）';


-- ============================================================
-- 模块六：船舶体系
-- 建表顺序: vessel_type_dict → vessel → vessel_name_history
--           → vessel_ais_history → vessel_dynamic
-- ============================================================

CREATE TABLE IF NOT EXISTS `vessel_type_dict` (
  `id`               INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`             VARCHAR(32)  NOT NULL               COMMENT '船型编码',
  `name`             VARCHAR(64)  NOT NULL               COMMENT '船型名称',
  `name_en`          VARCHAR(128)                        COMMENT '英文名称',
  `transport_type`   VARCHAR(32)           DEFAULT 'WATERWAY' COMMENT '运输类型',
  `applicable_goods` JSON                                COMMENT '适用货品类型列表',
  `min_tonnage`      INT                                 COMMENT '最小载重吨(DWT)',
  `max_tonnage`      INT                                 COMMENT '最大载重吨(DWT)',
  `description`      VARCHAR(512)                        COMMENT '描述',
  `sort_order`       INT          NOT NULL DEFAULT 0     COMMENT '排序',
  `status`           TINYINT      NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `audit_status`     TINYINT               DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `submitter_id`     BIGINT                              COMMENT '提交人ID',
  `auditor_id`       BIGINT                              COMMENT '审核人ID',
  `created_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_vtd_code` (`code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='船舶类型字典表';


CREATE TABLE IF NOT EXISTS `vessel` (
  `id`              INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `vessel_no`       VARCHAR(64)   NOT NULL               COMMENT '船舶检验证书号（业务唯一标识）',
  `vessel_name`     VARCHAR(128)  NOT NULL               COMMENT '当前船名',
  `mmsi`            VARCHAR(20)                          COMMENT 'AIS编号/MMSI',
  `call_sign`       VARCHAR(32)                          COMMENT '船舶呼号',
  `vessel_type_id`  BIGINT                               COMMENT '船舶类型ID',
  `deadweight`      INT                                  COMMENT '载重吨(DWT)',
  `gross_tonnage`   DECIMAL(12,2)                        COMMENT '总吨',
  `net_tonnage`     DECIMAL(12,2)                        COMMENT '净吨',
  `length`          DECIMAL(8,2)                         COMMENT '船长(m)',
  `breadth`         DECIMAL(8,2)                         COMMENT '船宽(m)',
  `depth`           DECIMAL(8,2)                         COMMENT '型深(m)',
  `max_draft`       DECIMAL(8,3)                         COMMENT '最大吃水(m)',
  `build_year`      INT                                  COMMENT '建造年份',
  `build_country`   VARCHAR(64)                          COMMENT '建造国家',
  `build_city`      VARCHAR(64)                          COMMENT '建造地',
  `home_port`       VARCHAR(128)                         COMMENT '船籍港',
  `flag`            VARCHAR(32)            DEFAULT '中国' COMMENT '船旗国',
  `owner_name`      VARCHAR(128)                         COMMENT '船东名称',
  `contact_phone`   VARCHAR(32)                          COMMENT '联系电话',
  `data_status`     TINYINT                DEFAULT 1     COMMENT '1=有效,0=注销',
  `is_deleted`      TINYINT                DEFAULT 0     COMMENT '0=正常,1=已删除',
  `audit_status`    TINYINT                DEFAULT 1     COMMENT '0=待审核,1=已通过,2=已驳回',
  `audit_remark`    VARCHAR(512)                         COMMENT '审核意见',
  `submitter_id`    BIGINT                               COMMENT '提交人ID',
  `auditor_id`      BIGINT                               COMMENT '审核人ID',
  `created_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`      DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_vessel_no` (`vessel_no`),
  KEY `idx_vessel_mmsi` (`mmsi`),
  KEY `idx_vessel_type_id` (`vessel_type_id`),
  KEY `idx_vessel_data_status` (`data_status`),
  CONSTRAINT `fk_vessel_type_id` FOREIGN KEY (`vessel_type_id`) REFERENCES `vessel_type_dict` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='船舶主档案表';


CREATE TABLE IF NOT EXISTS `vessel_name_history` (
  `id`            INT          NOT NULL AUTO_INCREMENT COMMENT '主键',
  `vessel_id`     BIGINT       NOT NULL               COMMENT '船舶ID',
  `old_name`      VARCHAR(128) NOT NULL               COMMENT '原船名',
  `new_name`      VARCHAR(128) NOT NULL               COMMENT '新船名',
  `change_reason` VARCHAR(256)                        COMMENT '变更原因',
  `changed_by`    BIGINT                              COMMENT '操作人ID',
  `changed_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '变更时间',
  `created_at`    DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_vnh_vessel_id` (`vessel_id`),
  CONSTRAINT `fk_vnh_vessel_id` FOREIGN KEY (`vessel_id`) REFERENCES `vessel` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='船舶历史船名表';


CREATE TABLE IF NOT EXISTS `vessel_ais_history` (
  `id`            INT         NOT NULL AUTO_INCREMENT COMMENT '主键',
  `vessel_id`     BIGINT      NOT NULL               COMMENT '船舶ID',
  `old_mmsi`      VARCHAR(20) NOT NULL               COMMENT '原MMSI',
  `new_mmsi`      VARCHAR(20) NOT NULL               COMMENT '新MMSI',
  `change_reason` VARCHAR(256)                       COMMENT '变更原因',
  `changed_by`    BIGINT                             COMMENT '操作人ID',
  `changed_at`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `created_at`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_vah_vessel_id` (`vessel_id`),
  CONSTRAINT `fk_vah_vessel_id` FOREIGN KEY (`vessel_id`) REFERENCES `vessel` (`id`) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='船舶AIS历史表（MMSI变更记录）';


CREATE TABLE IF NOT EXISTS `vessel_dynamic` (
  `id`                INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `vessel_id`         BIGINT        NOT NULL               COMMENT '船舶ID（每船唯一一条最新动态）',
  `current_longitude` DECIMAL(11,8)                        COMMENT '当前经度',
  `current_latitude`  DECIMAL(10,8)                        COMMENT '当前纬度',
  `current_node_id`   BIGINT                               COMMENT '当前所在节点ID',
  `vessel_status`     VARCHAR(32)            DEFAULT 'UNDERWAY' COMMENT 'EMPTY/LOADED/IN_PORT/ANCHORED/UNDERWAY/MAINTENANCE',
  `current_draft`     DECIMAL(8,3)                         COMMENT '当前吃水(m)',
  `dest_node_id`      BIGINT                               COMMENT '目的港节点ID',
  `eta`               DATETIME                             COMMENT '预计到达时间',
  `speed`             DECIMAL(5,2)                         COMMENT '当前航速(节)',
  `heading`           DECIMAL(5,2)                         COMMENT '当前船首向(度)',
  `cargo_info`        VARCHAR(256)                         COMMENT '当前载货信息',
  `remark`            VARCHAR(512)                         COMMENT '备注',
  `updated_by`        BIGINT                               COMMENT '更新人ID',
  `created_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`        DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_vd_vessel_id` (`vessel_id`),
  KEY `idx_vd_current_node_id` (`current_node_id`),
  KEY `idx_vd_dest_node_id` (`dest_node_id`),
  KEY `idx_vd_vessel_status` (`vessel_status`),
  CONSTRAINT `fk_vd_vessel_id`       FOREIGN KEY (`vessel_id`)       REFERENCES `vessel` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_vd_current_node_id` FOREIGN KEY (`current_node_id`) REFERENCES `transport_node` (`id`) ON DELETE SET NULL,
  CONSTRAINT `fk_vd_dest_node_id`    FOREIGN KEY (`dest_node_id`)    REFERENCES `transport_node` (`id`) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='船舶动态信息表（每船只保留最新一条）';


-- ============================================================
-- 模块七：航线体系
-- 建表顺序: shipping_route → shipping_route_path
-- ============================================================

CREATE TABLE IF NOT EXISTS `shipping_route` (
  `id`               INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `code`             VARCHAR(32)   NOT NULL               COMMENT '航线编码',
  `name`             VARCHAR(128)  NOT NULL               COMMENT '航线名称',
  `origin_region_id` BIGINT        NOT NULL               COMMENT '起始区域ID',
  `dest_region_id`   BIGINT        NOT NULL               COMMENT '目的区域ID',
  `distance_km`      DECIMAL(10,2)                        COMMENT '航线距离(km)',
  `duration_hours`   DECIMAL(8,2)                         COMMENT '标准航行时长(小时)',
  `description`      VARCHAR(512)                         COMMENT '航线描述',
  `sort_order`       INT           NOT NULL DEFAULT 0     COMMENT '排序',
  `status`           TINYINT       NOT NULL DEFAULT 1     COMMENT '1=启用,0=停用',
  `created_by`       BIGINT                               COMMENT '创建人ID',
  `created_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_sr_code` (`code`),
  KEY `idx_sr_origin_region_id` (`origin_region_id`),
  KEY `idx_sr_dest_region_id` (`dest_region_id`),
  KEY `idx_sr_status` (`status`),
  CONSTRAINT `fk_sr_origin_region` FOREIGN KEY (`origin_region_id`) REFERENCES `region` (`id`),
  CONSTRAINT `fk_sr_dest_region`   FOREIGN KEY (`dest_region_id`)   REFERENCES `region` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='商业航线表';


CREATE TABLE IF NOT EXISTS `shipping_route_path` (
  `id`                   INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `route_id`             BIGINT        NOT NULL               COMMENT '航线ID',
  `node_id`              BIGINT        NOT NULL               COMMENT '途经节点ID',
  `sequence`             INT           NOT NULL               COMMENT '序号（从1开始）',
  `distance_from_start`  DECIMAL(10,2)                        COMMENT '距起点距离(km)',
  `node_role`            VARCHAR(32)            DEFAULT 'WAYPOINT' COMMENT 'START/WAYPOINT/END（节点角色）',
  `created_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`           DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_srp_route_id` (`route_id`),
  KEY `idx_srp_node_id` (`node_id`),
  CONSTRAINT `fk_srp_route_id` FOREIGN KEY (`route_id`) REFERENCES `shipping_route` (`id`) ON DELETE CASCADE,
  CONSTRAINT `fk_srp_node_id`  FOREIGN KEY (`node_id`)  REFERENCES `transport_node` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='航线路径节点表';


-- ============================================================
-- 模块八：统计分析（heatmap_stat_daily）
-- ============================================================

CREATE TABLE IF NOT EXISTS `heatmap_stat_daily` (
  `id`               INT           NOT NULL AUTO_INCREMENT COMMENT '主键',
  `stat_date`        DATE          NOT NULL               COMMENT '统计日期',
  `node_id`          BIGINT        NOT NULL               COMMENT '运输节点ID',
  `stat_type`        VARCHAR(32)   NOT NULL               COMMENT 'CARGO_ORIGIN=装货统计,CARGO_DEST=卸货统计,VESSEL=运力统计',
  `cargo_count`      INT                    DEFAULT 0     COMMENT '货源数量',
  `total_tonnage`    DECIMAL(16,2)          DEFAULT 0     COMMENT '总吨位(吨)',
  `vessel_count`     INT                    DEFAULT 0     COMMENT '船舶数量',
  `total_deadweight` DECIMAL(16,2)          DEFAULT 0     COMMENT '总载重吨(DWT)',
  `created_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `updated_at`       DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_heatmap_daily` (`stat_date`, `node_id`, `stat_type`),
  KEY `idx_hsd_node_id` (`node_id`),
  KEY `idx_hsd_stat_date` (`stat_date`),
  CONSTRAINT `fk_hsd_node_id` FOREIGN KEY (`node_id`) REFERENCES `transport_node` (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='热力统计日表（每日定时聚合生成）';


SET FOREIGN_KEY_CHECKS = 1;

-- ============================================================
-- 初始化系统角色数据
-- ============================================================
INSERT IGNORE INTO `sys_role` (`code`, `name`, `description`, `status`, `sort_order`) VALUES
  ('SUPER_ADMIN', '超级管理员', '拥有所有权限', 1, 1),
  ('ADMIN',       '管理员',     '日常运营管理权限', 1, 2),
  ('OPERATOR',    '操作员',     '数据录入与审核权限', 1, 3),
  ('COLLECTOR',   '采集员',     '货源数据采集权限', 1, 4);

-- ============================================================
-- 初始化节点类型字典数据
-- ============================================================
INSERT IGNORE INTO `node_type` (`code`, `name`, `transport_mode`, `sort_order`, `status`) VALUES
  ('PORT',          '港口',   'WATERWAY', 1, 1),
  ('DOCK',          '码头',   'WATERWAY', 2, 1),
  ('ANCHORAGE',     '锚地',   'WATERWAY', 3, 1),
  ('INLAND_PORT',   '内河港', 'WATERWAY', 4, 1),
  ('WATERWAY_NODE', '航道节点', 'WATERWAY', 5, 1);
