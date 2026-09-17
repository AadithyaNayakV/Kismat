"""YOUR SKILLS — edit this file to control which jobs trigger Telegram alerts.

- Matching is case-insensitive and whole-word ("java" does not match "javascript",
  "go" does not match "google"). Symbols work: "c++", "c#", ".net", "node.js".
- A job is a match if its title/description/tags contain at least one skill.
- Leave MY_SKILLS empty ([]) to be alerted about every new job (spam guards still apply).
- After you edit this list, the next run re-tags all stored jobs automatically.
- The website shows every job regardless; skills are just filters/tags there.
"""

MY_SKILLS: list[str] = [
    "python",
    "javascript",
    "react",
    "sql",
    "django",
    "aws",
]

# Optional extra spellings. A job mentioning any alias is tagged with the main skill.
SKILL_ALIASES: dict[str, list[str]] = {
    "javascript": ["js", "ecmascript"],
    "react": ["react.js", "reactjs", "react native"],
    "aws": ["amazon web services"],
    "sql": ["mysql", "postgresql", "postgres", "sqlite", "t-sql", "pl/sql"],
    "python": ["python3"],
    "golang": ["go lang"],
    "node.js": ["nodejs", "node js"],
    "machine learning": ["ml"],
    "kubernetes": ["k8s"],
    "typescript": ["ts"],
}
