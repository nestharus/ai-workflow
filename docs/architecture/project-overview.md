# Project Overview

Doc ID: original-architecture-project-overview
Scope: general
Domain: none

Welcome to the Developing With AI 2.0 system. This repository implements an automated,
orchestrator-based AI workflow system where a central orchestrator service manages workflows and agent
invocations. AI agents act as specialized roles within a larger workflow coordinated by this service.

## System Description

This project implements an automated AI workflow system using a 5-role skeleton across four domains: Product,
UX, UI, and Technical. The architecture separates concerns between workflow orchestration and external event
handling through two core services.

## Core Components

### FastAPI Orchestrator Service

The central orchestrator service routes messages to workflows and coordinates agent execution. It receives
messages from agents, manages workflow state, and invokes other agents via `droid exec` subprocesses.

### Webhook Receiver Service

A standalone service handles GitHub integration by receiving webhooks, verifying signatures, and forwarding
validated events to the orchestrator for routing to appropriate workflows.

## Agent Interaction Model

Agents submit messages to the orchestrator rather than calling other agents directly. The orchestrator then:

- Routes messages to the appropriate workflow instance
- Manages workflow state and coordinates handoffs between roles
- Spawns `droid exec` subprocesses for agent execution
- Handles ticket claiming and PR comment routing

## Primary Goal

The system facilitates high-quality software development through structured, automated collaboration. By
enforcing role-based workflows and centralized orchestration, agents work together efficiently while
maintaining clear separation of responsibilities.
