job "mf-fail-job" {
  datacenters = ["dc1"]
  type = "batch"

  group "g" {
    task "fail" {
      driver = "docker"

      config {
        image   = "python:3.11-slim"
        command = "python"
        args    = ["-c", "import sys; print('failing'); sys.exit(2)"]
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}