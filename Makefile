.PHONY: help docker-test docker-diagnose clean-test-results clean-docker-test tidy-docker-test

.DEFAULT_GOAL := help

help:
	@printf "可用命令:\n"
	@printf "  make docker-test         - 启动 Docker 执行完整测试\n"
	@printf "  make docker-diagnose     - 启动 Docker 执行诊断脚本\n"
	@printf "  make clean-test-results  - 删除 test-results 目录\n"
	@printf "  make clean-docker-test   - 清理 Docker 测试容器（不删镜像/卷）\n"
	@printf "  make tidy-docker-test    - 清理容器, 删除 test-results ,开始测试\n"

docker-test:
	docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-test.sh

docker-diagnose:
	docker-compose -f docker/docker-compose.test.yml run --rm npm-test /project/docker/scripts/docker-diagnose.sh

clean-test-results:
	rm -rf test-results
	rm -rf node_modules
	rm -rf .venv

clean-docker-test:
	docker-compose -f docker/docker-compose.test.yml down --remove-orphans

tidy-docker-test: clean-docker-test clean-test-results docker-test
