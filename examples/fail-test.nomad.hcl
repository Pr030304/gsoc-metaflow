job "mf-fail-test" {
  datacenters = ["dc1"]
  type = "batch"

  group "g" {
    restart {
      attempts = 0
      mode     = "fail"
    }

    reschedule {
      attempts  = 0
      unlimited = false
    }

    task "fail" {
      driver = "docker"

      config {
        image   = "python:3.11-slim"
        command = "python"
        args    = ["-c", "import sys; print('failing once'); sys.exit(2)"]
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}