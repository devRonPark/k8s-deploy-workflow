# JPetStore Like

A small legacy Java web application used as a scanner fixture. It mimics an old
Maven + servlet project so the preanalyzer can detect a `maven` build with no
Dockerfile and no compose file.

## Build

```bash
mvn clean package
```

Produces a WAR to drop into a servlet container. There is no container image
here on purpose — the scanner should report `container_files` as not present.

## Layout

- `pom.xml` — Maven build (packaging: war)
- [schema](./src/main/resources/database/schema.sql) — HSQLDB bootstrap DDL
- `src/main/webapp/WEB-INF/web.xml` — servlet + JSP config

Note: this is a fixture, not a real app. Keep `pom.xml` and the two config files
stable — acceptance tests assert the exact artifact inventory derived from them.
