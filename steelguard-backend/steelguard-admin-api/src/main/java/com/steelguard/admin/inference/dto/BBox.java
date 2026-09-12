package com.steelguard.admin.inference.dto;

import lombok.Data;

/**
 * 检测框(像素绝对坐标, 左上角 x1,y1 / 右下角 x2,y2)
 */
@Data
public class BBox {

    private Double x1;

    private Double y1;

    private Double x2;

    private Double y2;
}
