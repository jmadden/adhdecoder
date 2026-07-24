# Connectors

## How tool references work

ADHDecoder is tool-agnostic. Skills describe workflows by **category**, not by
a specific product, using a `~~category` placeholder. Each user maps a category
to whatever tool they actually connect, in their instance `config.json` under
`sources`.

This is what lets ADHDecoder move between a work context (Jira + corporate
Slack + Salesforce) and personal life (personal email + a to-do app) without
changing the method.

## Categories for this plugin

| Category            | Placeholder             | Options                          |
| ------------------- | ----------------------- | -------------------------------- |
| Issue tracker       | `~~issue tracker`       | Jira, Linear, Asana, GitHub      |
| Chat                | `~~chat`                | Slack, Microsoft Teams, Discord  |
| Email               | `~~email`               | Gmail, Outlook                   |
| Calendar            | `~~calendar`            | Google Calendar, Outlook         |
| CRM                 | `~~crm`                 | Salesforce, HubSpot              |
| Docs                | `~~docs`                | Confluence, Notion               |
| Call intelligence   | `~~calls`               | Sybill, Gemini/Meet notes        |
| Knowledge base      | `~~knowledge`           | Obsidian vault, plain folder     |

## Notes

- Not every category needs to be connected. Enable only the sources you use in
  `config.json` (`sources[].enabled`).
- The **knowledge base** and **instance layer** are filesystem paths, not
  connectors, in the v0.1 filesystem adapter.
