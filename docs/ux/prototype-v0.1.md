# Lyra Hub Prototype v0.1

## Visual direction

- dark navy left navigation
- bright neutral content canvas
- blue as primary action color
- subtle blue-gray borders
- 10–14px card radius
- compact enterprise spacing
- clear status chips for running / warning / disabled
- no marketing hero treatment inside the authenticated product

The visual system should feel consistent with the newer Lyra administration pages while leaving each business application free to keep its own domain layout.

## P0 prototype screens

### 1. Overview

Purpose: answer “what applications do I have, what did I use recently, and is the AI platform healthy?”

Sections:

- greeting + global search
- My Applications
- Recent Use
- Today / Attention
- Gateway status
- Agent OS status
- application health summary

### 2. Application Center

Purpose: discover and manage applications.

Controls:

- search
- All / Installed / Available / Disabled
- category filter
- status filter
- cards with icon, name, category, version, status and primary action

### 3. Application Detail

Purpose: manage one application without entering its business pages.

Tabs:

- Overview
- Entry & Runtime
- Pages
- Plugins
- Permissions
- Capabilities
- Health & Logs
- Settings

Primary actions:

- Open Application
- Configure
- Enable / Disable

### 4. Page Configuration

Purpose: configure shared workspace navigation without rewriting application pages.

Layout:

- left: application/page tree
- center: navigation/page list with drag ordering
- right: selected item properties
- save / publish configuration

Editable:

- label
- icon
- visibility
- role visibility
- order
- default route
- slot/widget placement

### 5. Capability Center

Shows:

- Gateway
- Agent OS
- registered capabilities
- provider/owner
- status
- permission scope
- dependent applications

### 6. Operations

Shows:

- application health
- integration errors
- manifest validation errors
- capability dependency failures
- recent config changes
- audit events

## Responsive rule

Desktop is primary for v0.1. At <= 1024px:

- sidebar collapses to icon rail
- configuration page changes from three columns to two-step drawer editing
- application cards become two columns

At <= 768px:

- Hub allows launch/monitoring/basic settings
- advanced page designer is read-only or simplified
