job "mf-docker-test" {
  datacenters = ["dc1"]
  type = "batch"

  group "g" {
    task "echo" {
      driver = "docker"

      config {
        image   = "python:3.11-slim"
        command = "python"
        args    = ["-c", "print('nomad docker job ok')"]
      }

      resources {
        cpu    = 500
        memory = 256
      }
    }
  }
}





