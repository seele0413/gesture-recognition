(function attachPointerGeometry(root, factory) {
  const api = factory();
  if (typeof module === "object" && module.exports) {
    module.exports = api;
  } else {
    root.PointerGeometry = api;
  }
})(typeof globalThis !== "undefined" ? globalThis : this, function createPointerGeometry() {
  const EPSILON = 1e-9;

  function finitePoint(point) {
    return point && Number.isFinite(Number(point.x)) && Number.isFinite(Number(point.y));
  }

  function clamp(value, minimum, maximum) {
    return Math.min(maximum, Math.max(minimum, value));
  }

  function polygonArea(points) {
    let area = 0;
    for (let index = 0; index < points.length; index += 1) {
      const current = points[index];
      const next = points[(index + 1) % points.length];
      area += current.x * next.y - next.x * current.y;
    }
    return Math.abs(area) / 2;
  }

  function isConvexQuadrilateral(points) {
    if (!Array.isArray(points) || points.length !== 4 || !points.every(finitePoint)) return false;
    if (polygonArea(points) < 0.01) return false;
    let sign = 0;
    for (let index = 0; index < 4; index += 1) {
      const a = points[index];
      const b = points[(index + 1) % 4];
      const c = points[(index + 2) % 4];
      const cross = (b.x - a.x) * (c.y - b.y) - (b.y - a.y) * (c.x - b.x);
      if (Math.abs(cross) < 1e-5) return false;
      const nextSign = Math.sign(cross);
      if (sign && nextSign !== sign) return false;
      sign = nextSign;
    }
    return true;
  }

  function solveLinearSystem(rows) {
    const size = rows.length;
    const matrix = rows.map((row) => row.slice());
    for (let column = 0; column < size; column += 1) {
      let pivot = column;
      for (let row = column + 1; row < size; row += 1) {
        if (Math.abs(matrix[row][column]) > Math.abs(matrix[pivot][column])) pivot = row;
      }
      if (Math.abs(matrix[pivot][column]) < EPSILON) {
        throw new RangeError("四角校准点几何关系异常，请重新采集");
      }
      [matrix[column], matrix[pivot]] = [matrix[pivot], matrix[column]];
      const divisor = matrix[column][column];
      for (let item = column; item <= size; item += 1) matrix[column][item] /= divisor;
      for (let row = 0; row < size; row += 1) {
        if (row === column) continue;
        const factor = matrix[row][column];
        for (let item = column; item <= size; item += 1) {
          matrix[row][item] -= factor * matrix[column][item];
        }
      }
    }
    return matrix.map((row) => row[size]);
  }

  function solveHomography(sourcePoints, destinationPoints) {
    if (!isConvexQuadrilateral(sourcePoints) || !isConvexQuadrilateral(destinationPoints)) {
      throw new RangeError("四角必须按左上、右上、右下、左下顺序形成有效区域");
    }
    const equations = [];
    for (let index = 0; index < 4; index += 1) {
      const { x, y } = sourcePoints[index];
      const { x: u, y: v } = destinationPoints[index];
      equations.push([x, y, 1, 0, 0, 0, -u * x, -u * y, u]);
      equations.push([0, 0, 0, x, y, 1, -v * x, -v * y, v]);
    }
    const matrix = solveLinearSystem(equations);
    for (let index = 0; index < 4; index += 1) {
      const mapped = applyHomography(matrix, sourcePoints[index]);
      if (Math.hypot(mapped.x - destinationPoints[index].x, mapped.y - destinationPoints[index].y) > 1e-5) {
        throw new RangeError("四角校准误差过大，请重新采集");
      }
    }
    return matrix;
  }

  function applyHomography(matrix, point) {
    if (!Array.isArray(matrix) || matrix.length !== 8 || !matrix.every(Number.isFinite) || !finitePoint(point)) {
      throw new TypeError("无效的坐标映射参数");
    }
    const x = Number(point.x);
    const y = Number(point.y);
    const denominator = matrix[6] * x + matrix[7] * y + 1;
    if (Math.abs(denominator) < EPSILON) {
      throw new RangeError("坐标映射超出有效范围");
    }
    const mapped = {
      x: (matrix[0] * x + matrix[1] * y + matrix[2]) / denominator,
      y: (matrix[3] * x + matrix[4] * y + matrix[5]) / denominator,
    };
    if (!finitePoint(mapped)) throw new RangeError("坐标映射结果无效");
    return mapped;
  }

  function normalizedToClient(point, rect, mirrorX = false, homography = null) {
    if (!finitePoint(point) || !rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.top)
      || !Number.isFinite(rect.width) || !Number.isFinite(rect.height) || rect.width <= 0 || rect.height <= 0) {
      throw new TypeError("无效的指针坐标或画布尺寸");
    }
    const source = {
      x: clamp(Number(point.x), 0, 1),
      y: clamp(Number(point.y), 0, 1),
    };
    if (mirrorX) source.x = 1 - source.x;
    const mapped = homography ? applyHomography(homography, source) : source;
    return {
      x: rect.left + clamp(mapped.x, 0, 1) * rect.width,
      y: rect.top + clamp(mapped.y, 0, 1) * rect.height,
    };
  }

  function clientToWorld(clientPoint, rect, scrollLeft, scrollTop, zoom) {
    if (!finitePoint(clientPoint) || !rect || !Number.isFinite(rect.left) || !Number.isFinite(rect.top)
      || !Number.isFinite(scrollLeft) || !Number.isFinite(scrollTop) || !Number.isFinite(zoom) || zoom <= 0) {
      throw new TypeError("无效的画布坐标转换参数");
    }
    return {
      x: (clientPoint.x - rect.left + scrollLeft) / zoom,
      y: (clientPoint.y - rect.top + scrollTop) / zoom,
    };
  }

  function nodePositionFromPointer(worldPoint, grabOffset, canvasSize, nodeSize) {
    if (!finitePoint(worldPoint) || !finitePoint(grabOffset)
      || !canvasSize || !nodeSize
      || !Number.isFinite(Number(canvasSize.width)) || !Number.isFinite(Number(canvasSize.height))
      || !Number.isFinite(Number(nodeSize.width)) || !Number.isFinite(Number(nodeSize.height))) {
      throw new TypeError("无效的节点拖动参数");
    }
    const maxX = Math.max(0, Number(canvasSize.width) - Number(nodeSize.width));
    const maxY = Math.max(0, Number(canvasSize.height) - Number(nodeSize.height));
    return {
      x: clamp(Math.round(worldPoint.x - grabOffset.x), 0, maxX),
      y: clamp(Math.round(worldPoint.y - grabOffset.y), 0, maxY),
    };
  }

  return {
    applyHomography,
    clientToWorld,
    isConvexQuadrilateral,
    nodePositionFromPointer,
    normalizedToClient,
    solveHomography,
  };
});
