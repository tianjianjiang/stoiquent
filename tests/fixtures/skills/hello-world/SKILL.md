---
name: hello-world
description: A simple greeting skill for testing
version: "1.0"
tags:
  - example
  - greeting
tools:
  - name: greet
    description: Greet someone by name
    parameters:
      type: object
      properties:
        name:
          type: string
          description: The name to greet
      required:
        - name
---

# Hello World Skill

A simple skill that greets people by name.

## Usage

Ask the assistant to greet someone and it will use the `greet` tool.
