# syntax=docker/dockerfile:1
#
# Multi-stage build for the ROS 2 workspace.
#
#   base     ROS 2 + every rosdep dependency of the workspace (build, test, exec)
#   dev      base + dev tools and a non-root user; used by the devcontainer
#   build    colcon build of the workspace
#   runtime  slim ros-core image with only exec dependencies and the built install/
#   sim      browser-VNC desktop with Nav2 + Gazebo + TurtleBot3 for simulation
#
#   docker build --target runtime -t warehouse_amr .
#   docker compose up sim          # then open http://localhost:8080

ARG ROS_DISTRO=jazzy

# ---------------------------------------------------------------------------
FROM ros:${ROS_DISTRO}-ros-base AS base
ARG ROS_DISTRO
ENV DEBIAN_FRONTEND=noninteractive
WORKDIR /ros2_ws

# Only package manifests are copied here, so dependency layers stay cached
# until a package.xml changes.
COPY warehouse_package/package.xml src/warehouse_package/package.xml

RUN apt-get update \
    && rosdep update --rosdistro ${ROS_DISTRO} \
    && rosdep install --from-paths src --ignore-src -y \
    # Resolve exec-only dependencies to apt packages for the runtime stage
    && rosdep keys --from-paths src --ignore-src --dependency-types exec \
       | xargs -r rosdep resolve --rosdistro ${ROS_DISTRO} \
       | grep -v '^#' | tr ' ' '\n' | sed '/^$/d' | sort -u > /tmp/exec-deps.txt \
    && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------------------------
FROM base AS dev
ARG ROS_DISTRO
RUN apt-get update && apt-get install -y --no-install-recommends \
        sudo less vim gdb python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && echo 'ubuntu ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/ubuntu \
    && echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /home/ubuntu/.bashrc
USER ubuntu

# ---------------------------------------------------------------------------
FROM base AS build
ARG ROS_DISTRO
COPY warehouse_package src/warehouse_package
RUN . /opt/ros/${ROS_DISTRO}/setup.sh \
    && colcon build --event-handlers console_cohesion+

# ---------------------------------------------------------------------------
FROM ros:${ROS_DISTRO}-ros-core AS runtime
ARG ROS_DISTRO
ENV DEBIAN_FRONTEND=noninteractive
COPY --from=base /tmp/exec-deps.txt /tmp/exec-deps.txt
RUN apt-get update \
    && xargs -r -a /tmp/exec-deps.txt apt-get install -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/* /tmp/exec-deps.txt
COPY --from=build /ros2_ws/install /ros2_ws/install
COPY docker/ros_entrypoint.sh /ros_entrypoint.sh
ENTRYPOINT ["/ros_entrypoint.sh"]
CMD ["ros2", "run", "warehouse_package", "warehouse_brain"]

# ---------------------------------------------------------------------------
FROM tiryoh/ros2-desktop-vnc:${ROS_DISTRO} AS sim
ARG ROS_DISTRO
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
        ros-${ROS_DISTRO}-navigation2 \
        ros-${ROS_DISTRO}-nav2-bringup \
        ros-${ROS_DISTRO}-nav2-minimal-tb3-sim \
        ros-${ROS_DISTRO}-ros-gz \
    && rm -rf /var/lib/apt/lists/*
COPY --from=build /ros2_ws/install /ros2_ws/install
RUN echo "source /opt/ros/${ROS_DISTRO}/setup.bash" >> /etc/bash.bashrc \
    && echo "source /ros2_ws/install/setup.bash" >> /etc/bash.bashrc
