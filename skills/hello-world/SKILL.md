---
name: hello-world
description: A simple greeting skill
version: "1.0"
tags:
  - example
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
