-- ============================================================
-- ALU-GLASS Procurement System - MySQL 8 Schema
-- Run once:  mysql -u root -p < schema.sql
-- ============================================================
DROP DATABASE IF EXISTS alu_glass_procurement;
CREATE DATABASE alu_glass_procurement
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE alu_glass_procurement;

CREATE TABLE materials (
  code            VARCHAR(40)   PRIMARY KEY,
  category        VARCHAR(40)   NOT NULL,
  name            VARCHAR(120)  NOT NULL,
  specs           VARCHAR(300)  NOT NULL,
  uom             VARCHAR(16)   NOT NULL,
  current_stock   DECIMAL(14,4) NOT NULL DEFAULT 0,
  safety_stock    DECIMAL(14,4) NOT NULL DEFAULT 0,
  reorder_point   DECIMAL(14,4) NOT NULL DEFAULT 0,
  std_cost        DECIMAL(14,4) NOT NULL DEFAULT 0,
  supplier        VARCHAR(120)  NOT NULL,
  status          ENUM('low','reorder','safe') NOT NULL DEFAULT 'safe',
  tolerance       VARCHAR(120)  NULL,
  packaging       VARCHAR(120)  NULL,
  lead_time       VARCHAR(40)   NULL,
  bom_link        VARCHAR(120)  NULL,
  usage_rate      VARCHAR(40)   NULL,
  created_at      TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP     NULL,
  INDEX idx_mat_supplier (supplier),
  INDEX idx_mat_status (status),
  INDEX idx_mat_category (category)
) ENGINE=InnoDB;

CREATE TABLE suppliers (
  id              VARCHAR(40)  PRIMARY KEY,
  name            VARCHAR(120) NOT NULL UNIQUE,
  category        VARCHAR(80)  NOT NULL,
  tier            VARCHAR(40)  NOT NULL,
  score           INT          NOT NULL DEFAULT 0,
  price_metric    INT NULL, quality_metric  INT NULL, delivery_metric INT NULL,
  spec_metric     INT NULL, terms_metric    INT NULL, service_metric  INT NULL,
  payment_terms   VARCHAR(40)  NOT NULL,
  lead_time       VARCHAR(40)  NOT NULL,
  contact         VARCHAR(160) NOT NULL,
  otif            VARCHAR(16)  NULL,
  qc_rate         VARCHAR(16)  NULL,
  created_at      TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at      TIMESTAMP    NULL,
  CONSTRAINT chk_score CHECK (score BETWEEN 0 AND 100)
) ENGINE=InnoDB;

CREATE TABLE purchase_orders (
  po_number     VARCHAR(40)   PRIMARY KEY,
  vendor        VARCHAR(120)  NOT NULL,
  items         VARCHAR(400)  NOT NULL,
  amount_usd    DECIMAL(14,2) NOT NULL,
  due_date      DATE          NOT NULL,
  status        ENUM('Order Confirmed','In Transit','Arrived at Dock',
                     'Delayed','Received','Cancelled') NOT NULL DEFAULT 'Order Confirmed',
  alert         VARCHAR(80)   NOT NULL DEFAULT 'On Track',
  progress_pct  INT           NOT NULL DEFAULT 25,
  dock_action   VARCHAR(300)  NULL,
  created_at    TIMESTAMP     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at    TIMESTAMP     NULL,
  INDEX idx_po_vendor (vendor),
  INDEX idx_po_due (due_date),
  INDEX idx_po_status (status),
  CONSTRAINT fk_po_vendor FOREIGN KEY (vendor) REFERENCES suppliers(name)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT chk_progress CHECK (progress_pct BETWEEN 0 AND 100)
) ENGINE=InnoDB;

CREATE TABLE users (
  username       VARCHAR(32)  PRIMARY KEY,
  password_hash  VARCHAR(255) NOT NULL,
  full_name      VARCHAR(80)  NOT NULL,
  role           ENUM('admin','purchasing','engineer','finance') NOT NULL,
  status         ENUM('allowed','revoked') NOT NULL DEFAULT 'allowed',
  created_at     TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE audit_log (
  id         BIGINT AUTO_INCREMENT PRIMARY KEY,
  ts         VARCHAR(40)   NOT NULL,
  username   VARCHAR(40)   NOT NULL,
  action     VARCHAR(40)   NOT NULL,
  resource   VARCHAR(40)   NOT NULL,
  `key`      VARCHAR(80)   NULL,
  detail     JSON          NULL,
  INDEX idx_audit_ts (ts),
  INDEX idx_audit_user (username)
) ENGINE=InnoDB;

CREATE TABLE purchase_requisitions (
  pr_number      VARCHAR(40) PRIMARY KEY,
  department     VARCHAR(80) NOT NULL,
  requester      VARCHAR(120) NOT NULL,
  requested_by   VARCHAR(32) NULL,
  required_date  DATE NOT NULL,
  priority       ENUM('Routine','Urgent','Critical Line-Stop') NOT NULL,
  status         VARCHAR(60) NOT NULL,
  bom_project    VARCHAR(120) NULL,
  step1_decision VARCHAR(20) NULL, step1_by VARCHAR(80) NULL, step1_role VARCHAR(80) NULL,
  step1_date     VARCHAR(40) NULL, step1_notes VARCHAR(500) NULL, step1_user VARCHAR(32) NULL,
  step2_decision VARCHAR(20) NULL, step2_by VARCHAR(80) NULL, step2_role VARCHAR(80) NULL,
  step2_date     VARCHAR(40) NULL, step2_notes VARCHAR(500) NULL, step2_user VARCHAR(32) NULL,
  revisions      JSON NOT NULL,
  po_numbers     JSON NOT NULL,
  created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at     TIMESTAMP NULL,
  INDEX idx_pr_status (status),
  INDEX idx_pr_priority (priority),
  INDEX idx_pr_required (required_date)
) ENGINE=InnoDB;

CREATE TABLE pr_items (
  pr_number   VARCHAR(40)   NOT NULL,
  line_no     INT           NOT NULL,
  item_code   VARCHAR(40)   NOT NULL,
  item_name   VARCHAR(120)  NOT NULL,
  item_specs  VARCHAR(300)  NULL,
  quantity    DECIMAL(14,4) NOT NULL,
  uom         VARCHAR(16)   NOT NULL,
  unit_rate   DECIMAL(14,4) NOT NULL,
  PRIMARY KEY (pr_number, line_no),
  CONSTRAINT fk_item_pr FOREIGN KEY (pr_number)
    REFERENCES purchase_requisitions(pr_number) ON DELETE CASCADE,
  CONSTRAINT chk_qty CHECK (quantity > 0)
) ENGINE=InnoDB;

CREATE TABLE counters (
  name   VARCHAR(40) PRIMARY KEY,
  value  INT NOT NULL DEFAULT 0
) ENGINE=InnoDB;